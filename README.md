# kube-resource-analyzer

Analyze workload resource usage and automatically suggest adjustments to requests and limits


## Цели

1. Задать оптимальные requests/limits (выдавать рекомендации с возможностью планирования автоматической операции)
2. Уплотнить заполнение нод (выдавать рекомендации с возможностью планирования автоматической операции)
3. В случае, если с пунктом 1 возникает проблема (высокая волатильность потребления ресурсов) - выдавать рекомендации для оптимизации другими способами, такими как автоскейлинг от нагрузки.
4. Выдавать рекомендации для volumeless подов, чтобы пометить их как preemptible ready, либо non-ready (с помощью аннотации).
5. Сделать возможность автоматических операций оптимизации без подтверждения
6. Использовать отчет [gke_resource_usage](https://cloud.google.com/kubernetes-engine/docs/how-to/cluster-usage-metering).

Реализовать или использовать готовый автоскейлер, способный полностью усыплять приложение в ноль. Для внутренних проектов, таких как noty, myca. В случае noty, там наверное всё равно нужен es для сохранения ивентов открытия и тд. Но можно сделать для этого легковесный буфер, который будет периодически синхронизироваться, при запуске es.
Для поднятия сервиса можно использовать https://github.com/smpio/conbuf 

Проанализировать, какие нагрузки можно скинуть в preemptible (почти все веб поды). Выделить shared preem нод пул с taints. Поды нужно создавать с tolerations и affinity preferred during scheduling. Можно написать mutating webhook, который будет читать аннотацию preemptible ready.

Возможно, чтобы уплотнить нод пул, можно делать скейлинг пула в 0. Вслед за чем последует автоматический скейлинг до нужного размера. Это для пункта 2.


## Выбор хранилища метрик

Производительность оценивалась запросом одной метрики за последние 30 дней на стандартной misc ноде без ограничений.

* Postgres 12, 13: 150-200 ms на горячюю. Проблема - нет нормальной функции time_bucket, приходится пересылать много данных на клиент.
* Prometheus: нет обычной записи, только scrape. Не подходит.
* TimescaleDB: 40-70 ms на горячюю без hypertable. hypertable может ещё ускорить запросы.
* elasticsearch
* clickhouse
* influxdb

Пока остановился на timescaledb.


## Readings

* https://dl.acm.org/doi/pdf/10.1145/3342195.3387524
* https://habr.com/ru/news/t/499980/
* https://cloud.google.com/kubernetes-engine/docs/how-to/vertical-pod-autoscaling
* https://habr.com/ru/company/flant/blog/541642/
* https://github.com/kubernetes/autoscaler/tree/master/vertical-pod-autoscaler
* preem: https://cloud.google.com/compute/docs/instances/create-start-preemptible-instance#best_practices
