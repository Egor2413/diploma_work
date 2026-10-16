import requests

# ВАШИ ДАННЫЕ
BASE_URL = "http://127.0.0.1:8000"
# Вставьте сюда ваш ПОСЛЕДНИЙ access токен:
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0b2tlbl90eXBlIjoiYWNjZXNzIiwiZXhwIjoxNzkxMzcxMjk3LCJpYXQiOjE3OTEzNjc2OTcsImp0aSI6IjVjOTcxZDhlMmI3ZDQ3ZDA4MGMyYzhiNDcwYWNhNTFmIiwidXNlcl9pZCI6IjEifQ.Sknh9YkscBAihEVLA-9cUc2ZG4QVxBjA1EUn3FMxiso"

headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json"
}

# Отключаем прокси для локальных запросов
proxies = {
    'http': None,
    'https': None,
}


def test_api():
    print("--- 1. Проверяем список товаров ---")
    # Добавляем proxies=requests.get(..., proxies=proxies)
    r = requests.get(f"{BASE_URL}/api/products/", headers=headers, proxies=proxies)

    if r.status_code == 200:
        products = r.json()['results']
        if products:
            product_id = products[0]['id']
            print(f"✅ Найден товар ID: {product_id} - {products[0]['name']}")
        else:
            print("⚠️ Товаров нет в базе!")
            return
    else:
        print(f"❌ Ошибка товаров: {r.status_code}")
        return

    print("\n--- 2. Добавляем товар в корзину ---")
    data = {"product_id": product_id, "quantity": 1}
    r = requests.post(f"{BASE_URL}/api/cart/add_item/", json=data, headers=headers, proxies=proxies)
    print(f"Статус: {r.status_code}")
    print(f"Ответ: {r.json()}")

    print("\n--- 3. Смотрим корзину ---")
    r = requests.get(f"{BASE_URL}/api/cart/", headers=headers, proxies=proxies)
    print(f"Статус: {r.status_code}")
    print(f"Корзина: {r.json()}")
    print("\n--- 4. Оформляем заказ ---")
    data_order = {"address": "г. Москва, ул. Ленина, 1"}
    r = requests.post(f"{BASE_URL}/api/orders/", json=data_order, headers=headers, proxies=proxies)

    if r.status_code == 201:
        print("✅ Заказ успешно оформлен!")
        print(r.json())
    else:
        print(f"❌ Ошибка заказа: {r.status_code}, {r.text}")


if __name__ == "__main__":
    test_api()