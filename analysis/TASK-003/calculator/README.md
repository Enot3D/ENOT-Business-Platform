# Калькулятор TASK-003

Требуется Python 3.11+. Расчёт использует только стандартную библиотеку. Pytest 8.3.5 нужен для тестов. Запуск из корня репозитория.

```sh
cd analysis/TASK-003/calculator
python3 run.py > /tmp/enot-task003-results.json
python3 -m venv /tmp/enot-task003-venv
/tmp/enot-task003-venv/bin/python -m pip install -r requirements-test.txt
/tmp/enot-task003-venv/bin/python -m pytest -q
```

При наличии uv можно выполнить `uv run --with pytest==8.3.5 python -m pytest -q`. Калькулятор читает входы относительно собственного файла и выводит JSON в stdout. Данные и результаты расчёта не отправляются в сеть. Расчёты в [model.py](model.py) возвращают целые рубли и точные дроби для баллов. CLI сериализует баллы в числа JSON, а веса локальных тестов в точные строки дробей. `null` у порога означает, что при положительных фиксированных затратах и неположительной марже достичь безубыточности увеличением объёма невозможно.

[Поля и происхождение данных](../data-dictionary.md). [Версии, границы и интерпретация](../executive-summary.md). Стиль Python — PEP 8, UTF-8, обязательные проверки `python3 -m compileall -q .` и `python -m pytest -q`. Seed и число прогонов заданы в коде.
