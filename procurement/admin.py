import os

from django.conf import settings
from django.contrib import admin, messages
from django.shortcuts import redirect
from django.urls import path

from procurement.models import Product
from procurement.tasks import do_import


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "price", "quantity", "category", "supplier")
    actions = ["run_import_action"]

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path("run-import/", self.admin_site.admin_view(self.run_import_view), name="run-import"),
        ]
        return custom_urls + urls

    def run_import_view(self, request):
        """Запускает задачу do_import из админки"""
        filepath = os.path.join(settings.BASE_DIR, "data/shop.yaml")
        task = do_import.delay(filepath)
        messages.success(request, f"✅ Задача импорта (do_import) запущена в фоне! ID задачи: {task.id}")
        return redirect("/admin/procurement/product/")

    @admin.action(description="Запустить импорт товаров из YAML (Celery)")
    def run_import_action(self, request, queryset):
        filepath = os.path.join(settings.BASE_DIR, "data/shop.yaml")
        task = do_import.delay(filepath)
        messages.success(request, f"✅ Задача импорта запущена! ID: {task.id}")
