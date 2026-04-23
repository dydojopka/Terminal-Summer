# Terminal-Summer
Перенос легендарной визуальной новеллы ["Бесконечное лето"](https://store.steampowered.com/app/331470/Beskonechnoe_Leto/) в консольное окружение.  
Все сцены, спрайты и задники преобразуются в ANSI/ASCII-арты, а сам проект сделан на Python-фреймворке [textual](https://textual.textualize.io/).

Скриншоты:
|Everlasting Summer |Terminal Summer (ANSI) |Terminal Summer (ASCII) |
|:---:              |:---:                  |:---:                   |
|<img width="1920" height="1080" alt="ES_s1" src="https://github.com/user-attachments/assets/4db635bd-4de3-43c4-8b8c-f549911084c1" />|<img width="1920" height="1080" alt="TS_s1c" src="https://github.com/user-attachments/assets/92320e8a-c765-4ab5-b302-9af8c0e079c9" />|<img width="1920" height="1080" alt="TS_s1t" src="https://github.com/user-attachments/assets/c19a160c-9289-4ba7-9673-c02dc241cbf7" />|
|<img width="1920" height="1080" alt="ES_s2" src="https://github.com/user-attachments/assets/5a1c254f-a951-4600-9b41-0eb4a77a85fb" />|<img width="1920" height="1080" alt="TS_s2c" src="https://github.com/user-attachments/assets/a9e46ee6-a2d3-406b-9c75-40c0948d1cad" />|<img width="1920" height="1080" alt="TS_s2t" src="https://github.com/user-attachments/assets/f986ca57-b1bc-4da7-9cc1-14ad12027db8" />|
|<img width="1920" height="1080" alt="ES_s3" src="https://github.com/user-attachments/assets/c305fede-d4ab-4242-9619-e7e0e9ffe2dc" />|<img width="1920" height="1080" alt="TS_s3c" src="https://github.com/user-attachments/assets/d0573f1e-c3f5-4dfc-9a92-53ec987740f2" />|<img width="1920" height="1080" alt="TS_s3t" src="https://github.com/user-attachments/assets/afcb2856-4b5a-4b7c-b660-cf4c21ae2b9d" />|
|<img width="1920" height="1080" alt="ES_s4" src="https://github.com/user-attachments/assets/aae84f4d-4b43-443d-af84-cdb1b315ffc3" />|<img width="1920" height="1080" alt="TS_s4c" src="https://github.com/user-attachments/assets/13ca01bd-8046-4618-a27b-d32c34d7d763" />|<img width="1920" height="1080" alt="TS_s4t" src="https://github.com/user-attachments/assets/a2406404-1643-4369-8c1f-4456c343cbf4" />|
|<img width="1920" height="1080" alt="ES_s5" src="https://github.com/user-attachments/assets/1e4e7d26-e46f-4ede-b6c1-b0c3c2574094" />|<img width="1920" height="1080" alt="TS_s5c" src="https://github.com/user-attachments/assets/a71ae1a5-3b33-4d24-b583-e5ba19aecdfb" />|<img width="1920" height="1080" alt="TS_s5t" src="https://github.com/user-attachments/assets/3fadac2f-47df-4982-8b91-06c7eb4d83aa" />|
|<img width="1920" height="1080" alt="ES_s6" src="https://github.com/user-attachments/assets/2cedf435-22e9-4627-afa5-2b55d85599cf" />|<img width="1920" height="1080" alt="TS_s6c" src="https://github.com/user-attachments/assets/6882ecf7-1a28-4c61-9b79-367400639daf" />|<img width="1920" height="1080" alt="TS_s6t" src="https://github.com/user-attachments/assets/a0a07f5e-ada3-4f3f-b0e2-ebcbc1dc9e6b" />|


## Содержание
- [Технологии](#технологии)
- [Требования](#требования)
- [Использование](#использование)
  - [Сборка](#сборка)
- [FAQ](#faq)


## Технологии
- [Python 3.8+](https://www.python.org/)
- [Textual](https://github.com/Textualize/textual) - фреймворк для построения Rich TUI.
- [Pillow](https://python-pillow.org/) - обработка изображений и спрайтов.
- [pil2ansi](https://github.com/MatthiasValvekens/pil2ansi) - конвертация PNG в ANSI/SCII-арт.

## Требования
- **Python** версии 3.8 или выше
- **Git** для клонирования репозитория
- Терминал с поддержкой **True Color** (Windows Terminal, kitty или другие).

## Использование
Скачайте архив со [страницы последнего релиза](https://github.com/dydojopka/Terminal-Summer/releases/latest), разархивируйте и запустите из корня:

Linux:
```bash
./terminal-summer
```

Windows:
```shell
Terminal-Summer-Windows.exe
```


Или собрать самому:

### Сборка
#### Linux:
1. Клонирование репозитория:
```bash
git clone https://github.com/dydojopka/Terminal-Summer.git
cd Terminal-Summer
```

2. Установка зависимостей:
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install pyinstaller
```

3. Сборка:
```bash
bash scripts/build_and_run.sh
```

4. Запуск:
```bash
./terminal-summer
```


#### Windows:
1. Клонирование репозитория:
```shell
git clone https://github.com/dydojopka/Terminal-Summer.git
cd Terminal-Summer
```

2. Установка зависимостей:
```shell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
pip install pyinstaller
```

3. Сборка:
```shell
scripts\build_and_run.bat
```

4. Запуск:
```shell
Terminal-Summer-Windows.exe
```

> [!TIP]
> Если ANSI/ASCII-арт обрезается, даже если он должен полностью помещаться на экране - 
> закройте программу, откройте окно консоли во весь экран и после этого запустите программу снова.


## FAQ

### Зачем это вообще нужно?

Чтобы было.