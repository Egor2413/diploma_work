import os

import yaml
from django.core.management.base import BaseCommand

from procurement.models import Category, Product, Supplier


class Command(BaseCommand):
    help = "Импорт товаров из YAML файлов"

    def add_arguments(self, parser):
        parser.add_argument("filepath", type=str, help="Путь к YAML файлу")

    def handle(self, *args, **options):
        filepath = options["filepath"]

        if not os.path.exists(filepath):
            self.stdout.write(self.style.ERROR(f"Файл {filepath} не найден"))
            return

        with open(filepath, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        # 1. Создаем или обновляем поставщика
        shop_info = data.get("shop", {})
        supplier, created = Supplier.objects.update_or_create(
            name=shop_info.get("name"), defaults={"url": shop_info.get("url")}
        )
        status = "создан" if created else "обновлен"
        self.stdout.write(self.style.SUCCESS(f'Поставщик "{supplier.name}" {status}'))

        # 2. Обрабатываем категории
        categories_map = {}
        for cat in data.get("categories", []):
            category, _ = Category.objects.get_or_create(name=cat["name"])
            categories_map[cat["id"]] = category

        # 3. Обрабатываем товары
        products_created = 0
        for item in data.get("products", []):
            category_id = item.get("category")
            category = categories_map.get(category_id)

            if not category:
                self.stdout.write(
                    self.style.WARNING(f'Категория с ID {category_id} не найдена для товара {item["name"]}')
                )
                continue

            Product.objects.update_or_create(
                name=item["name"],
                supplier=supplier,
                defaults={
                    "price": item["price"],
                    "quantity": item.get("quantity", 0),
                    "category": category,
                    "specifications": item.get("specifications", {}),
                },
            )
            products_created += 1

        self.stdout.write(self.style.SUCCESS(f"Успешно обработано {products_created} товаров"))
