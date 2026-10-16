import os
import yaml
from celery import shared_task
from django.core.mail import send_mail
from procurement.models import Supplier, Category, Product


@shared_task(name='send_email')
def send_email(subject, message, recipient_list, from_email='admin@shop.com'):
    """
    Задача отправки email.
    Это именно тот send_email, который требует задание.
    """
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=from_email,
            recipient_list=recipient_list,
            fail_silently=False,
        )
        return f"Email отправлен: {subject} -> {recipient_list}"
    except Exception as e:
        return f"Ошибка отправки: {str(e)}"


@shared_task(name='do_import')
def do_import(filepath):
    """
    Задача импорта товаров из YAML файла.
    Это именно тот do_import, который требует задание.
    """
    if not os.path.exists(filepath):
        return f"❌ Файл {filepath} не найден"

    with open(filepath, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)

    # 1. Создаем/обновляем поставщика
    shop_info = data.get('shop', {})
    supplier, _ = Supplier.objects.update_or_create(
        name=shop_info.get('name'),
        defaults={'url': shop_info.get('url')}
    )

    # 2. Обрабатываем категории
    categories_map = {}
    for cat in data.get('categories', []):
        category, _ = Category.objects.get_or_create(name=cat['name'])
        categories_map[cat['id']] = category

    # 3. Обрабатываем товары
    products_created = 0
    for item in data.get('products', []):
        category_id = item.get('category')
        category = categories_map.get(category_id)

        if not category:
            continue

        Product.objects.update_or_create(
            name=item['name'],
            supplier=supplier,
            defaults={
                'price': item['price'],
                'quantity': item.get('quantity', 0),
                'category': category,
                'specifications': item.get('specifications', {})
            }
        )
        products_created += 1

    return f"✅ Импортировано {products_created} товаров из {filepath}"