"""查詢小工具。"""

from sqlalchemy import inspect as sa_inspect

from extensions import db


def fast_count(query):
    """等同 query.count()，但只數主鍵。

    Query.count() 會產生 SELECT count(*) FROM (SELECT <所有欄位> ...)：MySQL 要把整張寬表
    （含 TEXT 欄位）物化成衍生表再數，資料一多就很慢，而且同一個頁面常常要數好幾次。
    這裡直接 SELECT count(主鍵)，保留原本的 JOIN / WHERE，結果完全相同。"""
    entity = query.column_descriptions[0]["entity"]
    pk = sa_inspect(entity).primary_key[0]
    return query.order_by(None).with_entities(db.func.count(pk)).scalar() or 0
