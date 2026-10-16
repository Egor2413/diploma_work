from django.db import models
from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """Модель пользователя (Клиент или Поставщик)."""
    phone = models.CharField(max_length=20, blank=True, null=True, verbose_name="Телефон")

    class Meta:
        db_table = 'users'
        verbose_name = "Пользователь"
        verbose_name_plural = "Пользователи"


class Supplier(models.Model):
    """Модель поставщика."""
    name = models.CharField(max_length=255, verbose_name="Название поставщика")
    url = models.URLField(blank=True, null=True, verbose_name="Сайт поставщика")
    is_active = models.BooleanField(default=True, verbose_name="Принимает заказы")

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Поставщик"
        verbose_name_plural = "Поставщики"


class Category(models.Model):
    """Категории товаров."""
    name = models.CharField(max_length=255, unique=True, verbose_name="Название категории")

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Категория"
        verbose_name_plural = "Категории"


class Product(models.Model):
    """Модель товара."""
    name = models.CharField(max_length=255, verbose_name="Название товара")
    category = models.ForeignKey(Category, related_name='products', on_delete=models.CASCADE, verbose_name="Категория")
    supplier = models.ForeignKey(Supplier, related_name='products', on_delete=models.CASCADE, verbose_name="Поставщик")
    price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Цена")
    quantity = models.PositiveIntegerField(default=0, verbose_name="Количество на складе")
    description = models.TextField(blank=True, null=True, verbose_name="Описание")

    # JSON поле для характеристик (например: {"цвет": "красный", "размер": "XL"})
    specifications = models.JSONField(default=dict, blank=True, null=True, verbose_name="Характеристики")

    def __str__(self):
        return f"{self.name} ({self.price} руб.)"

    class Meta:
        verbose_name = "Товар"
        verbose_name_plural = "Товары"
        unique_together = ('name', 'supplier')


class Cart(models.Model):
    """Корзина пользователя."""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='cart')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Корзина пользователя {self.user.username}"


class CartItem(models.Model):
    """Товар внутри корзины."""
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)

    def __str__(self):
        return f"{self.product.name} x {self.quantity}"

    @property
    def total_price(self):
        return self.product.price * self.quantity


class Order(models.Model):
    """Заказ."""
    STATUS_CHOICES = [
        ('NEW', 'Новый'),
        ('PROCESSING', 'В обработке'),
        ('SHIPPED', 'Отправлен'),
        ('DELIVERED', 'Доставлен'),
        ('CANCELLED', 'Отменен'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='orders')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='NEW')
    address = models.TextField(verbose_name="Адрес доставки")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Заказ #{self.id} от {self.user.username}"


class OrderItem(models.Model):
    """Товар внутри заказа."""
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    price = models.DecimalField(max_digits=10, decimal_places=2)  # Цена фиксируется на момент заказа

    def __str__(self):
        return f"{self.product.name} x {self.quantity}"
