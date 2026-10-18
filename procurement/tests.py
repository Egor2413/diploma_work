from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from procurement.models import Category, Product, Supplier


class ProductAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.supplier = Supplier.objects.create(name="Test Supplier")
        self.category = Category.objects.create(name="Test Category")
        self.product = Product.objects.create(
            name="Test Product",
            price=1000,
            quantity=5,
            category=self.category,
            supplier=self.supplier,
        )

    def test_product_list(self):
        """Тест получения списка товаров"""
        response = self.client.get("/api/products/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 1)

    def test_product_detail(self):
        """Тест получения одного товара"""
        response = self.client.get(f"/api/products/{self.product.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["name"], "Test Product")

    def test_category_list(self):
        """Тест получения списка категорий"""
        response = self.client.get("/api/categories/")
        self.assertEqual(response.status_code, 200)


class AuthAPITest(TestCase):
    def test_register_user(self):
        """Тест регистрации нового пользователя"""
        data = {
            "username": "testuser",
            "email": "test@test.com",
            "password": "TestPass123!",
            "password_confirm": "TestPass123!",
        }
        response = self.client.post("/api/register/", data, format="json")
        self.assertEqual(response.status_code, 201)

    def test_get_token(self):
        """Тест получения JWT токена"""
        # Сначала регистрируем
        self.client.post(
            "/api/register/",
            {
                "username": "tokenuser",
                "email": "token@test.com",
                "password": "TestPass123!",
                "password_confirm": "TestPass123!",
            },
            format="json",
        )

        # Получаем токен
        response = self.client.post(
            "/api/token/",
            {
                "username": "tokenuser",
                "password": "TestPass123!",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data)
