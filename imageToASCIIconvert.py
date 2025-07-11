import os
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- Настройка Selenium ---
def init_driver():
    chrome_options = Options()
    chrome_options.add_argument("--start-maximized")
    # chrome_options.add_argument("--headless")  # Раскоментировать, если нужно без GUI
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-logging"])
    service = Service()
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver

# --- Установка размера ASCII ---
def set_ascii_size(driver, size_label):
    wait = WebDriverWait(driver, 10)
    size_button = wait.until(
        EC.presence_of_element_located((By.CSS_SELECTOR, 'button.control-btn[data-text="Medium"]'))
    )
    
    if size_label == "SMALL":
        size_button.click()
        time.sleep(0.3)
        size_button.click()
    elif size_label == "LARGE":
        size_button.click()
    # MEDIUM — ничего не делаем

# --- Основной скрипт ---
def main():
    input_folder = input("Введите путь к папке с изображениями (jpg/png): ").strip()
    if not os.path.isdir(input_folder):
        print("❌ Папка не найдена.")
        return

    output_folder = input("Введите путь для сохранения ASCII файлов: ").strip()
    os.makedirs(output_folder, exist_ok=True)

    size_input = input("Выберите размер ASCII-арта (SMALL / MEDIUM / LARGE): ").strip().upper()
    if size_input not in ["SMALL", "MEDIUM", "LARGE"]:
        print("❌ Неверный размер. Используйте SMALL / MEDIUM / LARGE.")
        return

    valid_ext = ('.jpg', '.jpeg', '.png')
    images = [f for f in os.listdir(input_folder) if f.lower().endswith(valid_ext)]

    if not images:
        print("В папке нет подходящих изображений.")
        return

    driver = init_driver()
    wait = WebDriverWait(driver, 20)
    driver.get("https://itoa.hex.dance/")

    # Установка нужного размера
    set_ascii_size(driver, size_input)

    for img_name in images:
        full_path = os.path.join(input_folder, img_name)
        print(f"Обработка: {img_name}")

        try:
            upload_input = driver.find_element(By.CSS_SELECTOR, 'input[type="file"]')
            upload_input.send_keys(full_path)

            # Ждём ASCII результат
            ascii_element = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'pre.ascii-output'))
            )

            #time.sleep(0.5)
            ascii_art = ascii_element.text

            txt_name = os.path.splitext(img_name)[0] + ".txt"
            txt_path = os.path.join(output_folder, txt_name)

            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(ascii_art)

            print(f"✅ Сохранено: {txt_path}")

            # driver.refresh()
            time.sleep(0.2)

            # # Повторная настройка размера после перезагрузки
            # set_ascii_size(driver, size_input)

        except Exception as e:
            print(f"❌ Ошибка с {img_name}: {e}")

    driver.quit()
    print("\n--- Готово! Все изображения обработаны. ---")

if __name__ == "__main__":
    main()
