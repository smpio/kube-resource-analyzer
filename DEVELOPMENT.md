# Запуск для разработки

В этой схеме все существующие сервисы остаются в Kubernetes. Локально запускаются
только Django API в PyCharm и React UI в VS Code; PostgreSQL/TimescaleDB и Redis
доступны через ручные `kubectl port-forward`. Docker Compose для этой схемы не нужен.

Инструкция сверена с исходным кодом и сохранёнными манифестами 22 сентября 2026 года.
В рамках задачи документации стек не запускался и кластер не изменялся.
Запуск API/UI из IDE и чтение данных подтверждены отдельной задачей запуска;
ниже приведены последовательность воспроизведения и границы выполненной проверки.
Фактические версии образов, переменные работающих Pod и доступность кластера требуют
проверки при повторении в другом окружении.

По отчёту отдельной задачи запуска от 22 сентября 2026 года:
зависимости установлены, `manage.py check` и сборка frontend прошли, сервисы
`postgres`/`redis` доступны в `yc-yc1`, туннели
`127.0.0.1:5432` и `127.0.0.1:6379` работают, очередь worker не переопределена
и по конфигурации должна использоваться `default` (отправкой задания это не проверялось).
Проверка SELECT подтвердила БД `postgres` и таблицу
`kra_workload`, Redis ответил на PING. В PyCharm конфигурация `runserver` запустила
Django 4.0.10 на `127.0.0.1:8000` без ошибок system check. В VS Code сохранённая
build task скомпилировала UI на `127.0.0.1:3000`, затем F5 активировал конфигурацию
`localhost:3000`. GET `/workloads/` вернул HTTP 200 и JSON-список из 333 записей
(число относится только к моменту проверки); frontend также вернул HTTP 200.
В браузере отобразились реальные workloads, графики и предложения. Кнопки Apply
не нажимались, миграции, worker, collectors и конфигурация кластера не изменялись.

## 1. Схема и исходные каталоги

```text
Локально                                      Kubernetes: namespace kube-kra
Chrome → React :3000 → Django API :8000
                          │
                          ├─ 127.0.0.1:5432 ── port-forward → svc/postgres → TimescaleDB
                          └─ 127.0.0.1:6379 ── port-forward → svc/redis
                                                              ↑
                                          Celery worker ──────┘
                                               ├─ общая БД
                                               └─ Kubernetes API (Events, patches)
                                          pod/metric/oom collectors → общая БД
                                          CronJob cleanup, make-suggestions → общая БД
```

| Компонент | Где находится / запускается |
| --- | --- |
| Backend | `kube-resource-analyzer`, PyCharm |
| Frontend | `kra-frontend`, VS Code |
| Манифесты | `infra/kube/kube-kra` |
| PostgreSQL с TimescaleDB, Redis, Celery, collectors, CronJob | Уже работают в кластере; оставить как есть |

Пути к проектам отсчитываются от общей родительской папки репозиториев.
Каждый блок команд, начинающийся с `cd`, выполняйте из этой папки
(например, в новом терминале).
Работа локального API с общей БД и очередью влияет на настоящее окружение.
Локальный Celery worker запускать не нужно: задания исполняет существующий worker,
его код берётся из кластерного образа, а не из локальных правок Python.

## 2. Подготовить зависимости

Нужны Git с доступом к SSH-репозиторию `smpio/python-utils`, Python, Node.js/npm,
kubectl, доступ к нужному kube context, PyCharm, VS Code и Chrome.
Для kubeconfig с Yandex Cloud exec-аутентификацией также нужен настроенный `yc`.

Backend использует [python-utils](.gitmodules) как submodule; `utils` — символьная
ссылка на `.submodules/python-utils/utils`. При пустом submodule приложение не импортируется.

```sh
cd kube-resource-analyzer
git submodule update --init --recursive
git submodule status
python3 -m venv venv
venv/bin/python -m pip install -r requirements.txt -r requirements.dev.txt 'kubernetes==23.6.0' 'urllib3<2'
venv/bin/python -m pip check
```

Базовый образ — Python 3.14.7 из [Dockerfile](Dockerfile). `requirements.txt`
ограничивает Django веткой 5.2 (не ниже 5.2.8), а `utils/django/__init__.py`
закреплённого submodule проверяет эту же ветку. Django 5.2 поддерживает Python 3.14,
начиная с 5.2.8.
Ограничение `urllib3<2` добавлено для системного Python с LibreSSL на этой машине.

Полного lock-файла Python нет: установка не гарантирует идентичный набор версий или
совместимость со всеми новыми Python. Не обновляйте `python-utils` на произвольную
ветку до завершения проверки совместимости.

```sh
cd kra-frontend
npm ci --no-audit --no-fund
```

Frontend использует React 17 и `react-scripts` 4.0.3. `npm ci` в отдельной задаче
прошёл с Node.js 26.9.0. Сборка с webpack 4.44.2 также прошла командой
`NODE_OPTIONS=--openssl-legacy-provider npm run build`; запуск dev server из
VS Code также подтверждён. В `package.json` нет
ограничения `engines`; совместимость произвольного нового Node.js не подтверждена.
Используйте `package-lock.json`, не заменяйте `npm ci` обновлением зависимостей.

## 3. Выбрать кластер и проверить сервисы

```sh
kubectl config get-contexts
kubectl config current-context
```

Выберите контекст целевого кластера. В отдельной задаче на этой машине найден
`yc-yc1`; не переносите это имя в другое окружение без проверки.
Убедитесь, что текущий контекст соответствует целевому кластеру: команды ниже
используют текущий контекст kubectl.

```sh
kubectl -n kube-kra get services postgres redis
kubectl -n kube-kra get deployment celery timescale redis
kubectl -n kube-kra get cronjobs
```

По манифестам `svc/postgres:5432` выбирает Deployment `timescale`, а
`svc/redis:6379` — Deployment `redis`. Сервис `postgres` ведёт в PostgreSQL
с расширением TimescaleDB, а не в отдельную локальную БД.

Проверьте адреса БД/Redis и очередь у работающего worker: `envFrom` Deployment
ссылается на ConfigMap `app-env`, также возможны явные `env` и настройки образа.
Для проверки только очереди без вывода всего ConfigMap:

```sh
kubectl -n kube-kra get configmap app-env \
  -o jsonpath='{.data.CELERY_DEFAULT_QUEUE}{"\n"}'
kubectl -n kube-kra get deployment celery \
  -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="CELERY_DEFAULT_QUEUE")].value}{"\n"}'
```

Пустой вывод означает отсутствие этой переменной в проверенном месте, а не доказанное
имя очереди. В сохранённых манифестах она отсутствует; `DEV_ENV=no` в Dockerfile
и закреплённый python-utils дают очередь **`default`**. В режиме разработки
по умолчанию получается **`kra`**, поэтому требуется явное переопределение.
При отличиях живого Deployment/образа используйте его фактическую очередь и подключения.
Не копируйте весь кластерный ConfigMap в локальный `.env` и не публикуйте секреты.

## 4. Открыть два ручных туннеля

В двух отдельных терминалах:

```sh
kubectl -n kube-kra port-forward --address 127.0.0.1 svc/postgres 5432:5432
```

```sh
kubectl -n kube-kra port-forward --address 127.0.0.1 svc/redis 6379:6379
```

Дождитесь `Forwarding from 127.0.0.1:...` и оставьте процессы работать.
Если порт занят, используйте, например, `15432:5432` / `16379:6379` и замените
локальные порты во всех соответствующих URL ниже. После разрыва соединения или
смены Pod туннель может потребовать ручного перезапуска.
При проверенном запуске старые туннели уже завершились и были восстановлены этими
командами; наличие ранее открытого терминала не гарантирует работающего соединения.

## 5. Настроить локальный Django

Создайте или дополните `.env` в корне backend. Он исключён из Git.
Следующие значения соответствуют умолчаниям кода для кластерного образа и
сохранённым манифестам; фактическое окружение проверьте на шаге 3:

```dotenv
DEV_ENV=yes
DJANGO_DEBUG=yes
LOGGING=console
DATABASE_URL=postgres://postgres@127.0.0.1:5432/postgres
CACHE_URL=redis://127.0.0.1:6379/0
CELERY_BROKER_URL=redis://127.0.0.1:6379/1
CELERY_RESULT_BACKEND_URL=redis://127.0.0.1:6379/2
CELERY_DEFAULT_QUEUE=default
CELERY_ALWAYS_EAGER=no
KUBE_IN_CLUSTER=no
KUBE_API_URL=http://127.0.0.1:8001
```

Если в живом окружении есть пароль или другое имя БД, внесите их только в свой
локальный `.env` (спецсимволы credentials в URL должны быть URL-encoded).
`postgres` — имя БД по кластерному умолчанию; локальное dev-умолчание `kra` здесь
не подходит. Одинаково важны **одна БД, один Redis, broker DB `/1` и одна очередь**
у API и worker. Redis `/0` используется для cache/locks, `/2` — result backend;
переменная результата называется именно `CELERY_RESULT_BACKEND_URL`.
`CELERY_ALWAYS_EAGER=no` оставляет исполнение заданий кластерному worker.

`.env` читается относительно рабочего каталога при включённом `DEV_ENV`.
Переменные среды процесса имеют приоритет: проверьте, что PyCharm не наследует
противоречащие значения, в особенности `DEV_ENV=no`, DB URL и очередь.
`DEV_ENV=yes` также включает CORS для UI на другом локальном порту.

Для обычного чтения UI достаточно двух туннелей. `KUBE_API_URL` задаёт конфигурацию
Kubernetes-клиента при импорте, но сам по себе не открывает соединение.
Если локально отлаживаемому коду действительно нужен прямой Kubernetes API,
в третьем терминале можно вручную запустить:

```sh
kubectl proxy --address=127.0.0.1 --port=8001
```

Это отдельный путь к Kubernetes API; PostgreSQL/Redis port-forward его не заменяют.
Применяющий adjustment кластерный worker использует собственную конфигурацию и
ServiceAccount `app`, поэтому отсутствие локального proxy не запрещает применение.

## 6. Запустить API в PyCharm

1. Откройте `kube-resource-analyzer` как проект.
2. Выберите интерпретатор `<корень backend>/venv/bin/python`.
3. Выберите сохранённую конфигурацию [runserver](.run/runserver.run.xml).
   Проверьте Script path `$PROJECT_DIR$/manage.py`, Parameters `runserver`,
   Working directory `$PROJECT_DIR$` и интерпретатор проекта.
   Module должен называться `kube-resource-analyzer`: старое значение
   `kube-resources-analyzer` исправлено в основном checkout отдельной задачей запуска.
4. Запустите Run или Debug. Ожидаемый адрес — `http://127.0.0.1:8000/`.

Сохранённая конфигурация задаёт `PYTHONUNBUFFERED=1` и наследует окружение;
настройки подключений берутся из `.env`. При проблемах импорта проверьте submodule
и выбранный venv. После настройки `.env` можно выполнить
`venv/bin/python manage.py check` из корня backend; эта проверка прошла в отдельной
задаче, но не заменяет запуск HTTP-сервера. При предупреждении о миграциях не запускайте `migrate` на общей
БД автоматически: сначала согласуйте версии локального кода и кластерного приложения.

## 7. Запустить UI в VS Code

1. Откройте `kra-frontend` как папку проекта.
2. Выполните Terminal → Run Build Task (на macOS Cmd+Shift+B), дождитесь
   `Compiled successfully`. Затем в Run and Debug выберите `localhost:3000`
   и запустите Start Debugging (F5). Именно эта последовательность проверена.
3. `.vscode/launch.json` запускает Chrome по адресу `http://localhost:3000`
   с `preLaunchTask: ${defaultBuildTask}`. Задача из `.vscode/tasks.json`
   запускает `npm start` с `BROWSER=none`, чтобы npm не открывал второй браузер.
   В основном checkout задача также задаёт `HOST=127.0.0.1` и
   `NODE_OPTIONS=--openssl-legacy-provider` для совместимости старого webpack
   с используемым Node.js. В другой копии проверьте эти значения в `options.env`.
4. Проверьте открывшийся UI и активную панель отладки. В `src/api.ts` адрес API уже задан как
   `http://localhost:8000/`; менять его для этой схемы не требуется.

Если VS Code ждёт завершения фоновой задачи (у неё пустой `problemMatcher`),
проверьте вывод задачи и дождитесь готовности dev server. После этого продолжите
отладку через Debug Anyway, если такая кнопка показана, либо откройте
`http://localhost:3000` вручную. Не запускайте второй `npm start` на том же порту.
Этот запасной вариант не потребовался в подтверждённом запуске и отдельно не проверялся.

## 8. Проверить чтение, не создавая заданий

```sh
curl --fail --silent --show-error http://localhost:8000/workloads/ -o /dev/null
curl --fail --silent --show-error http://localhost:8000/suggestions/ -o /dev/null
curl --fail --silent --show-error http://localhost:3000/ -o /dev/null
```

Для списка workloads завершающий `/` обязателен: проверенный `/workloads/`
вернул HTTP 200, а `/workloads` — HTTP 404.

В UI откройте список workloads и карточку с графиками. В DevTools → Network
проверьте успешные GET-запросы к `localhost:8000`, отсутствие CORS/500 ошибок.
GET-обработчики читают общую БД; проверка не подтверждает работоспособность отправки
Celery-заданий или права worker на Kubernetes API. Для этого не нужно отправлять
тестовое изменение в рабочую очередь.

Не нажимайте **Apply now**, **Apply tonight** и кнопку игнорирования OOM
в рамках проверки чтения. Не вызывайте POST/PUT/PATCH/DELETE: API использует
`ModelViewSet` и не является read-only.

## Что делает Celery и какие действия меняют окружение

Поведение подтверждено [views.py](kra/views.py),
[signal_handlers.py](kra/signal_handlers.py) и [apply_adjustment.py](kra/tasks/apply_adjustment.py):

| Действие | Последствие |
| --- | --- |
| Сохранение OOM, включая изменение `is_ignored` из UI | Запись в общей БД и Celery-задача пересчёта рекомендации |
| Создание новой OOM-записи | Дополнительно Celery-задача создаёт Kubernetes Event `ContainerOOM` |
| Apply now / создание или изменение adjustment через API | Запись adjustment и задача `apply_adjustment`; worker меняет resources workload через Kubernetes PATCH |
| Apply tonight / adjustment с будущим `scheduled_for` | Worker повторно ставит задачу с `eta=scheduled_for`; локальные процессы могут уже быть остановлены к моменту применения |
| Другие изменяющие методы API | Могут менять или удалять общие данные; в текущем `urls.py` маршрут `summaries` также связан с `AdjustmentViewSet` |

PATCH заменяет объект `resources` контейнера на `limits.memory` и `requests.cpu`,
а не только меняет отображение UI. После применения сохраняется результат и
обновляются связанные рекомендации/сводки. Проверяйте локальные правки задач отдельно:
работающий кластерный worker автоматически их не получает.

Ночные задания запускает **Kubernetes CronJob**, не локальный Celery beat:

| CronJob | Команда | Расписание по сохранённым манифестам |
| --- | --- | --- |
| `cleanup` | `manage.py cleanup` | 03:00, `Europe/Moscow` |
| `make-suggestions` | `manage.py get_suggestions --update-all` | 03:15, `Europe/Moscow` |

`cleanup` удаляет старые записи и синхронно вызывает применение просроченных
adjustments без результата; это не просто уборка. `get_suggestions --update-all`
пересчитывает сводки и рекомендации с записью в БД. Не запускайте эти команды,
collectors, миграции или дополнительный worker ради проверки локального UI.
Время Apply tonight задаёт UI через `scheduled_for`; оно не является расписанием CronJob.

## 9. Остановить только локальную сессию

1. Остановите Run/Debug backend в PyCharm.
2. Остановите отладку Chrome в VS Code и отдельно завершите фоновую npm-задачу
   через Tasks → Terminate Task (либо Ctrl+C в её терминале).
3. Завершите оба `kubectl port-forward` через Ctrl+C и `kubectl proxy`, если запускали.

Не останавливайте и не перезапускайте Deployment, CronJob, collectors, Redis,
TimescaleDB или Celery в кластере. Остановка локального API/туннелей **не отменяет**
уже отправленные или запланированные задания.

## Источники и границы проверки

В backend проверены [настройки](kra/settings.py), [инициализация](kra/__init__.py),
[маршруты](kra/urls.py), [Celery](kra/celery.py),
[очистка](kra/management/commands/cleanup.py),
[пересчёт](kra/management/commands/get_suggestions.py), а также настройки python-utils
на закреплённой ревизии из основного checkout. В worktree документа submodule
на момент проверки не инициализирован.

В соседних репозиториях проверены `src/api.ts`, `.vscode/tasks.json`,
`.vscode/launch.json`, `src/components/WorkloadCard.tsx`,
`src/components/ContainerCard.tsx`; манифесты `_core/Service/{postgres,redis}.yaml`,
`_core/ConfigMap/app-env.yaml`, `apps/Deployment/{celery,timescale,redis}.yaml`
и `batch/CronJob/{cleanup,make-suggestions}.yaml`.
Секреты из конфигурации в документ не перенесены.
