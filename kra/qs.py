from django.db.models import Func, Max, Value, DateTimeField


class TimeBucket(Func):
    function = 'time_bucket'


def to_buckets(qs, bucket_size_sec, time_field, *fields, aggr=Max):
    bucket_size = f'{bucket_size_sec} seconds'
    p = '_bucket_'

    qs = qs\
        .annotate(**{
            p+time_field: TimeBucket(Value(bucket_size), time_field, output_field=DateTimeField())
        })\
        .values(p+time_field)\
        .order_by(p+time_field)

    for field in fields:
        qs = qs.annotate(**{
            p+field: aggr(field),
        })

    for result in qs:
        result[time_field] = result[p+time_field]
        del result[p+time_field]
        for field in fields:
            result[field] = result[p+field]
            del result[p+field]

    return qs
