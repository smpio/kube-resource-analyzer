# kube-resource-analyzer

Analyze workload resource usage and automatically suggest adjustments to requests and limits


## Цели

Задать оптимальные requests/limits для подов в кластере.
И детектить проблемы с их потреблением (высокая волательность, утечки и т.д.).

Изучить:
* https://dl.acm.org/doi/pdf/10.1145/3342195.3387524
* https://habr.com/ru/news/t/499980/


## Не цели

Близкие задачи, которые будут решаться в других проектах. Объединить с https://github.com/smpio/wiki/blob/master/Backend/cluster-optimization.md

### Уплотнение

Уплотнение заполнения нод. Возможно, чтобы уплотнить нод пул, можно делать скейлинг пула в 0. Вслед за чем последует автоматический скейлинг до нужного размера.

### Preemptible

Проанализировать, какие нагрузки можно скинуть в preemptible (почти все веб поды). Выделить shared preem нод пул с taints. Поды нужно создавать с tolerations и affinity preferred during scheduling. Можно написать mutating webhook, который будет читать аннотацию preemptible ready.

Выдавать рекомендации для volumeless подов, чтобы пометить их как preemptible ready, либо non-ready (с помощью аннотации).

* https://cloud.google.com/compute/docs/instances/create-start-preemptible-instance#best_practices

### Autoscaling

Реализовать или использовать готовый автоскейлер, способный полностью усыплять приложение в ноль. Для внутренних проектов, таких как noty, myca. В случае noty, там наверное всё равно нужен es для сохранения ивентов открытия и тд. Но можно сделать для этого легковесный буфер, который будет периодически синхронизироваться, при запуске es.
Для поднятия сервиса можно использовать https://github.com/smpio/conbuf 

* https://habr.com/ru/company/flant/blog/541642/
* https://cloud.google.com/kubernetes-engine/docs/how-to/vertical-pod-autoscaling
* https://github.com/kubernetes/autoscaler/tree/master/vertical-pod-autoscaler

### Оценка потребления ресурсов проектами

Использовать отчет [gke_resource_usage](https://cloud.google.com/kubernetes-engine/docs/how-to/cluster-usage-metering).

### Оптимизация подов

* ручной анализ загруженности web воркеров и их скейлинг
* анализ загруженности web воркеров и авто-скейлинг
* автоперезапуск подов с утечками памяти (указывать частоту перезапуска в аннотации)
* threaded workers + смотри личный TODO
* pgpool, pgbouncer

## Выбор хранилища метрик

Производительность оценивалась запросом одной метрики за последние 30 дней на стандартной misc ноде без ограничений.

* Postgres 12, 13: 150-200 ms на горячюю. Проблема - нет нормальной функции time_bucket, приходится пересылать много данных на клиент.
* Prometheus: нет обычной записи, только scrape. Не подходит.
* TimescaleDB: 40-70 ms на горячюю без hypertable. hypertable может ещё ускорить запросы.
* elasticsearch
* clickhouse
* influxdb

Пока остановился на timescaledb.
