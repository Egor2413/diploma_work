import logging
import os

from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.utils.decorators import method_decorator
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
    queryset = Category.objects.all()
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
        return Response(
            {"message": "Пользователь успешно зарегистрирован", "user_id": user.id}, status=status.HTTP_201_CREATED
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

        # Создаем заказ
        order = Order.objects.create(user=request.user, address=address)

        total_amount = 0
        order_items_data = []

        for item in cart.items.all():
            OrderItem.objects.create(
                order=order, product=item.product, quantity=item.quantity, price=item.product.price
            )
            total_amount += item.total_price
            order_items_data.append(f"{item.product.name} x {item.quantity}")

        cart.items.all().delete()

        # Логирование успешного заказа
        logger.info(f"Создан заказ #{order.id}: user={request.user.username}, amount={total_amount}, address={address}")

        # Отправка email
        items_str = ", ".join(order_items_data)
        send_email.delay(
            subject=f"Заказ #{order.id} принят!",
            message=f"Здравствуйте, {request.user.username}!\nВаш заказ на сумму {total_amount} руб. принят.\nАдрес: {address}\nТовары: {items_str}",
            recipient_list=[request.user.email],
        )
        logger.info(f"Задача отправки email клиенту для заказа #{order.id} поставлена в очередь")

        send_email.delay(
            subject=f"Новый заказ #{order.id} от {request.user.username}",
            message=f"Новый заказ!\nКлиент: {request.user.username}\nСумма: {total_amount}\nАдрес: {address}\nТовары:\n{items_str}",
            recipient_list=["admin@example.com"],
        )
        logger.info(f"Задача отправки email админу для заказа #{order.id} поставлена в очередь")

        return Response(OrderSerializer(order).data, status=status.HTTP_201_CREATED)


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
