import logging
import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.db import connection
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.views.decorators.cache import cache_page
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics, permissions, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import AllowAny, IsAdminUser
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from procurement.tasks import do_import, send_email

from .models import Cart, CartItem, Category, Order, OrderItem, Product, Supplier
from .serializers import (
    CartSerializer,
    CategorySerializer,
    OrderSerializer,
    ProductSerializer,
    RegisterSerializer,
    SupplierSerializer,
)

logger = logging.getLogger("procurement")


class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.all().order_by("id")
    serializer_class = ProductSerializer
    permission_classes = [permissions.AllowAny]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["category", "supplier"]
    search_fields = ["name", "description"]
    ordering_fields = ["price", "quantity", "name"]
    ordering = ["id"]

    @method_decorator(cache_page(60 * 5))  # Кэш на 5 минут
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)


class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all().order_by("id")
    serializer_class = CategorySerializer
    permission_classes = [permissions.AllowAny]

    @method_decorator(cache_page(60 * 5))
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)


class SupplierViewSet(viewsets.ModelViewSet):
    queryset = Supplier.objects.all()
    serializer_class = SupplierSerializer
    permission_classes = [permissions.AllowAny]

    @method_decorator(cache_page(60 * 5))
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        try:
            send_email.delay(
                subject="Добро пожаловать в Procurement Service!",
                message=(
                    f"Здравствуйте, {user.username}!\n"
                    f"Ваша регистрация успешно завершена.\n"
                    f"Теперь вы можете оформлять заказы."
                ),
                recipient_list=[user.email],
            )
        except Exception as exc:
            logger.error(f"Не удалось поставить письмо в очередь: {exc}")

        return Response(
            {"message": "Пользователь успешно зарегистрирован. Проверьте вашу почту.", "user_id": user.id},
            status=status.HTTP_201_CREATED,
        )


class CartViewSet(viewsets.ModelViewSet):
    serializer_class = CartSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Cart.objects.filter(user=self.request.user)

    def get_object(self):
        cart, created = Cart.objects.get_or_create(user=self.request.user)
        return cart

    @action(detail=False, methods=["post"])
    def add_item(self, request):
        cart = self.get_object()
        product_id = request.data.get("product_id")
        quantity = int(request.data.get("quantity", 1))

        try:
            product = Product.objects.get(id=product_id)
        except Product.DoesNotExist:
            return Response({"error": "Товар не найден"}, status=status.HTTP_404_NOT_FOUND)

        cart_item, created = CartItem.objects.update_or_create(
            cart=cart, product=product, defaults={"quantity": quantity}
        )

        if not created:
            cart_item.quantity += quantity
            cart_item.save()

        return Response(CartSerializer(cart).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["delete"])
    def clear(self, request):
        cart = self.get_object()
        cart.items.all().delete()
        return Response({"message": "Корзина очищена"}, status=status.HTTP_200_OK)


class OrderViewSet(viewsets.ModelViewSet):
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [UserRateThrottle]

    def get_queryset(self):
        return Order.objects.filter(user=self.request.user)

    def create(self, request, *args, **kwargs):
        cart = Cart.objects.filter(user=request.user).first()
        if not cart or not cart.items.exists():
            logger.warning(f"Попытка создать заказ с пустой корзиной: user={request.user.username}")
            return Response({"error": "Корзина пуста"}, status=status.HTTP_400_BAD_REQUEST)

        address = request.data.get("address")
        if not address:
            return Response({"error": "Укажите адрес доставки"}, status=status.HTTP_400_BAD_REQUEST)

        # 1. Группируем товары корзины по поставщикам
        from collections import defaultdict

        supplier_items = defaultdict(list)
        for item in cart.items.all():
            supplier_items[item.product.supplier].append(item)

        created_orders = []
        total_amount_all = 0

        # 2. Создаем ОТДЕЛЬНЫЙ заказ для каждого поставщика
        for supplier, items in supplier_items.items():
            order = Order.objects.create(user=request.user, supplier=supplier, address=address)

            order_total = 0
            invoice_lines = []

            for item in items:
                OrderItem.objects.create(
                    order=order, product=item.product, quantity=item.quantity, price=item.product.price
                )
                order_total += item.total_price
                invoice_lines.append(
                    invoice_lines.append(
                        f"• {item.product.name} | Кол-во: {item.quantity} | "
                        f"Цена: {item.product.price} руб. | Сумма: {item.total_price} руб."
                    )
                )

            total_amount_all += order_total
            created_orders.append(order)

            # 3. Формируем накладную
            invoice_text = (
                f"=== НАКЛАДНАЯ №{order.id} ===\n"
                f"Дата: {order.created_at.strftime('%d.%m.%Y %H:%M')}\n"
                f"Поставщик: {supplier.name}\n"
                f"Получатель: {request.user.username}\n"
                f"Адрес доставки: {address}\n"
                f"{'=' * 40}\n"
                f"СПИСОК ТОВАРОВ:\n" + "\n".join(invoice_lines) + f"\n"
                f"{'=' * 40}\n"
                f"ИТОГО К ОТГРУЗКЕ: {order_total} руб.\n"
                f"Статус: Ожидает исполнения\n"
            )

            # 4. Отправляем накладную ПОСТАВЩИКУ (или админу, если у поставщика нет email)
            supplier_email = supplier.email or "admin@example.com"
            send_email.delay(
                subject=f"Новая накладная №{order.id} для исполнения",
                message=invoice_text,
                recipient_list=[supplier_email],
            )
            logger.info(f"Накладная №{order.id} отправлена поставщику {supplier.name} на {supplier_email}")

        # 5. Очищаем корзину
        cart.items.all().delete()

        # 6. Сводное письмо клиенту
        client_msg = (
            f"Здравствуйте, {request.user.username}!\n"
            f"Ваш заказ на общую сумму {total_amount_all} руб. принят в обработку.\n"
            f"Заказ разделен на {len(created_orders)} поставки по разным поставщикам.\n"
            f"Адрес доставки: {address}"
        )
        send_email.delay(
            subject=f"Заказ принят! (Разделен на {len(created_orders)} поставки)",
            message=client_msg,
            recipient_list=[request.user.email],
        )
        logger.info(
            f"Создано {len(created_orders)} заказов для user={request.user.username} на сумму {total_amount_all}"
        )

        # 7. Возвращаем данные всех созданных заказов
        return Response(OrderSerializer(created_orders, many=True).data, status=status.HTTP_201_CREATED)


class RunImportView(generics.GenericAPIView):
    """
    View для запуска задачи импорта (do_import).
    Доступен только администраторам (IsAdminUser).
    """

    permission_classes = [IsAdminUser]

    def post(self, request):
        filepath = request.data.get("filepath", "data/shop.yaml")
        full_path = os.path.join(settings.BASE_DIR, filepath)

        # Запускаем задачу do_import в фоне
        task = do_import.delay(full_path)

        return Response(
            {"status": "Задача импорта запущена", "task_id": task.id, "filepath": filepath},
            status=status.HTTP_202_ACCEPTED,
        )


@api_view(["GET"])
@permission_classes([AllowAny])
def health_check(request):
    """
    Health check endpoint для мониторинга работоспособности сервиса.
    Используется load balancer'ами и системами мониторинга.
    """
    status_data = {
        "status": "healthy",
        "service": "procurement-service",
        "version": "1.0.0",
    }

    # Проверка БД
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        status_data["database"] = "connected"
    except Exception as e:
        status_data["status"] = "unhealthy"
        status_data["database"] = f"error: {str(e)}"
        return JsonResponse(status_data, status=500)

    return JsonResponse(status_data)


User = get_user_model()


class PasswordResetRequestView(generics.GenericAPIView):
    """Запрос на сброс пароля (отправка email со ссылкой)"""

    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get("email")
        if not email:
            return Response({"error": "Email обязателен"}, status=status.HTTP_400_BAD_REQUEST)

        users = User.objects.filter(email=email)
        if users.exists():
            user = users.first()
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)

            reset_link = f"http://127.0.0.1:8000/api/auth/password-reset/confirm/?uid={uid}&token={token}"

            send_email.delay(
                subject="Восстановление пароля",
                message=(
                    f"Здравствуйте, {user.username}!\n"
                    f"Для сброса пароля перейдите по ссылке:\n{reset_link}\n"
                    f"Если вы не запрашивали сброс, проигнорируйте это письмо."
                ),
                recipient_list=[user.email],
            )
            logger.info(f"Отправлена ссылка для сброса пароля пользователю {user.username}")

        return Response(
            {"message": "Если пользователь с таким email существует, инструкция отправлена."}, status=status.HTTP_200_OK
        )


class PasswordResetConfirmView(generics.GenericAPIView):
    """Подтверждение сброса пароля и установка нового"""

    permission_classes = [AllowAny]

    def post(self, request):
        uid = request.data.get("uid")
        token = request.data.get("token")
        new_password = request.data.get("new_password")

        if not all([uid, token, new_password]):
            return Response({"error": "uid, token и new_password обязательны"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user_id = force_str(urlsafe_base64_decode(uid))
            user = User.objects.get(pk=user_id)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            return Response({"error": "Неверная ссылка"}, status=status.HTTP_400_BAD_REQUEST)

        if default_token_generator.check_token(user, token):
            user.set_password(new_password)
            user.save()
            logger.info(f"Пароль успешно сброшен для пользователя {user.username}")
            return Response({"message": "Пароль успешно изменен."}, status=status.HTTP_200_OK)
        else:
            return Response({"error": "Неверный или просроченный токен"}, status=status.HTTP_400_BAD_REQUEST)
