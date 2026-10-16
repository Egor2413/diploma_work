import os
from rest_framework import viewsets, permissions, generics, status
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAdminUser
from rest_framework.decorators import action
from django.conf import settings

from .models import Product, Category, Supplier, Cart, CartItem, Order, OrderItem
from .serializers import (
    ProductSerializer, CategorySerializer, SupplierSerializer,
    RegisterSerializer, CartSerializer, OrderSerializer
)

# Импортируем именно те задачи, которые требуются в задании
from procurement.tasks import send_email, do_import


class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.all().order_by('id')
    serializer_class = ProductSerializer
    permission_classes = [permissions.AllowAny]


class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [permissions.AllowAny]


class SupplierViewSet(viewsets.ModelViewSet):
    queryset = Supplier.objects.all()
    serializer_class = SupplierSerializer
    permission_classes = [permissions.AllowAny]


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(
            {"message": "Пользователь успешно зарегистрирован", "user_id": user.id},
            status=status.HTTP_201_CREATED
        )


class CartViewSet(viewsets.ModelViewSet):
    serializer_class = CartSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Cart.objects.filter(user=self.request.user)

    def get_object(self):
        cart, created = Cart.objects.get_or_create(user=self.request.user)
        return cart

    @action(detail=False, methods=['post'])
    def add_item(self, request):
        cart = self.get_object()
        product_id = request.data.get('product_id')
        quantity = int(request.data.get('quantity', 1))

        try:
            product = Product.objects.get(id=product_id)
        except Product.DoesNotExist:
            return Response({"error": "Товар не найден"}, status=status.HTTP_404_NOT_FOUND)

        cart_item, created = CartItem.objects.update_or_create(
            cart=cart,
            product=product,
            defaults={'quantity': quantity}
        )

        if not created:
            cart_item.quantity += quantity
            cart_item.save()

        return Response(CartSerializer(cart).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['delete'])
    def clear(self, request):
        cart = self.get_object()
        cart.items.all().delete()
        return Response({"message": "Корзина очищена"}, status=status.HTTP_200_OK)


class OrderViewSet(viewsets.ModelViewSet):
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Order.objects.filter(user=self.request.user)

    def create(self, request, *args, **kwargs):
        cart = Cart.objects.filter(user=request.user).first()
        if not cart or not cart.items.exists():
            return Response({"error": "Корзина пуста"}, status=status.HTTP_400_BAD_REQUEST)

        address = request.data.get('address')
        if not address:
            return Response({"error": "Укажите адрес доставки"}, status=status.HTTP_400_BAD_REQUEST)

        # Создаем заказ
        order = Order.objects.create(user=request.user, address=address)

        total_amount = 0
        order_items_data = []

        # Переносим товары из корзины в заказ
        for item in cart.items.all():
            OrderItem.objects.create(
                order=order,
                product=item.product,
                quantity=item.quantity,
                price=item.product.price
            )
            total_amount += item.total_price
            order_items_data.append(f"{item.product.name} x {item.quantity}")

        # Очищаем корзину
        cart.items.all().delete()

        # --- ОТПРАВКА EMAIL ЧЕРЕЗ CELERY (Задача send_email) ---
        items_str = ", ".join(order_items_data)

        # 1. Письмо клиенту
        send_email.delay(
            subject=f"Заказ #{order.id} принят!",
            message=f"Здравствуйте, {request.user.username}!\nВаш заказ на сумму {total_amount} руб. принят.\nАдрес: {address}\nТовары: {items_str}",
            recipient_list=[request.user.email],
        )

        # 2. Письмо администратору
        send_email.delay(
            subject=f"Новый заказ #{order.id} от {request.user.username}",
            message=f"Новый заказ!\nКлиент: {request.user.username}\nСумма: {total_amount}\nАдрес: {address}\nТовары:\n{items_str}",
            recipient_list=["admin@example.com"],
        )

        return Response(OrderSerializer(order).data, status=status.HTTP_201_CREATED)


class RunImportView(generics.GenericAPIView):
    """
    View для запуска задачи импорта (do_import).
    Доступен только администраторам (IsAdminUser).
    """
    permission_classes = [IsAdminUser]

    def post(self, request):
        filepath = request.data.get('filepath', 'data/shop.yaml')
        full_path = os.path.join(settings.BASE_DIR, filepath)

        # Запускаем задачу do_import в фоне
        task = do_import.delay(full_path)

        return Response({
            "status": "Задача импорта запущена",
            "task_id": task.id,
            "filepath": filepath
        }, status=status.HTTP_202_ACCEPTED)