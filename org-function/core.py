# -*- coding: utf-8 -*-
"""org-function: 조직(팀/그룹/파트)별 기능(Function1/Function2) 조회 모듈.

두 개의 핵심 함수:
  1. build_org_function_db()  : 원본 SSOT DB를 읽어 조직별 기능 로컬 DB(SQLite)를 생성
  2. get_org_functions()      : 조직명(팀/그룹/파트, 일부 생략 가능)으로 기능 목록 반환

열 지정 방식: MySQL 등 RDB는 스프레드시트처럼 1행 값이 라벨이 아니라
테이블 스키마에 열 이름이 정의되어 있다. 따라서 columns 매핑에는
**원본 테이블의 실제 열 이름**(SHOW COLUMNS / information_schema 로 확인)을 넣는다.
열 이름을 모르면 list_source_columns() 로 조회할 수 있다.

원본 DB 접속 정보는 .env 에서 읽는다:
  SSOT_DB_IP, SSOT_DB_PORT, SSOT_DB_DBNAME, SSOT_DB_ID, SSOT_DB_PW
  SSOT_DB_DIALECT (선택, 기본 "mysql+pymysql". postgresql+psycopg2 등 SQLAlchemy dialect)
  SSOT_DB_TABLE   (선택, 원본 테이블명 기본값)
  SSOT_COL_TEAM / SSOT_COL_GROUP / SSOT_COL_PART / SSOT_COL_FUNC1 / SSOT_COL_FUNC2
                  (선택, 열 이름 기본값 — 함수 인자가 우선)
"""

import os
import sqlite3
from typing import Dict, List, Optional

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text

DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "org_functions.sqlite")

# 조직별 기능 DB 스키마 (grp: "group"은 SQL 예약어라 회피)
_SCHEMA = """
CREATE TABLE IF NOT EXISTS org_function (
    team      TEXT,
    grp       TEXT,
    part      TEXT,
    function1 TEXT,
    function2 TEXT
);
CREATE INDEX IF NOT EXISTS idx_of_team ON org_function(team);
CREATE INDEX IF NOT EXISTS idx_of_grp  ON org_function(grp);
CREATE INDEX IF NOT EXISTS idx_of_part ON org_function(part);
"""


def _norm(v) -> Optional[str]:
    """셀 값 정규화: 공백 제거, 빈 값은 None."""
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _source_engine(env_file: Optional[str] = None):
    """.env 의 SSOT_DB_* 값으로 SQLAlchemy 엔진 생성."""
    load_dotenv(env_file, override=False)
    ip = os.environ["SSOT_DB_IP"]
    port = os.environ["SSOT_DB_PORT"]
    dbname = os.environ["SSOT_DB_DBNAME"]
    user = os.environ["SSOT_DB_ID"]
    pw = os.environ["SSOT_DB_PW"]
    dialect = os.environ.get("SSOT_DB_DIALECT", "mysql+pymysql")
    url = f"{dialect}://{user}:{pw}@{ip}:{port}/{dbname}"
    return create_engine(url)


def build_org_function_db(
    source_table: Optional[str] = None,
    columns: Optional[Dict[str, str]] = None,
    db_path: str = DEFAULT_DB_PATH,
    env_file: Optional[str] = None,
) -> int:
    """원본 SSOT DB를 읽어 조직별 기능 DB(SQLite)를 (재)생성한다.

    Args:
        source_table: 원본 테이블명. 생략 시 .env 의 SSOT_DB_TABLE.
        columns: 논리 역할 → 원본 테이블의 **실제 열 이름** 매핑.
            (스프레드시트의 1행 라벨이 아니라 DB 스키마의 열 이름.
             모르면 list_source_columns() 로 확인.)
            {"team": "팀", "group": "그룹", "part": "파트",
             "function1": "Function1", "function2": "Function2"}
            생략된 키는 .env 의 SSOT_COL_* 값으로 채운다.
        db_path: 생성할 SQLite 파일 경로.
        env_file: .env 경로(생략 시 기본 탐색).

    Returns:
        적재된 행 수(전체 5열 완전중복 제거 후).
    """
    load_dotenv(env_file, override=False)
    source_table = source_table or os.environ["SSOT_DB_TABLE"]

    env_cols = {
        "team": os.environ.get("SSOT_COL_TEAM"),
        "group": os.environ.get("SSOT_COL_GROUP"),
        "part": os.environ.get("SSOT_COL_PART"),
        "function1": os.environ.get("SSOT_COL_FUNC1"),
        "function2": os.environ.get("SSOT_COL_FUNC2"),
    }
    cols = {**env_cols, **(columns or {})}
    missing = [k for k, v in cols.items() if not v]
    if missing:
        raise ValueError(f"열 이름 미지정: {missing} (columns 인자 또는 SSOT_COL_* 환경변수 필요)")

    engine = _source_engine(env_file)

    # 지정한 열 이름이 실제 스키마에 있는지 선검증 (오타 시 SQL 에러보다 명확한 메시지)
    actual = {c["name"] for c in inspect(engine).get_columns(source_table)}
    unknown = [f"{k}={v!r}" for k, v in cols.items() if v not in actual]
    if unknown:
        raise ValueError(
            f"테이블 {source_table!r} 에 없는 열: {unknown}. "
            f"실제 열 목록: {sorted(actual)}"
        )
    q = engine.dialect.identifier_preparer.quote
    order = ["team", "group", "part", "function1", "function2"]
    select_cols = ", ".join(q(cols[k]) for k in order)
    sql = f"SELECT {select_cols} FROM {q(source_table)}"

    with engine.connect() as conn:
        raw_rows = conn.execute(text(sql)).fetchall()

    # 5열 전체가 중복인 라인 소거 후 조직(팀→그룹→파트) 기준 정렬
    dedup = {tuple(_norm(v) for v in row) for row in raw_rows}
    dedup.discard((None, None, None, None, None))
    rows = sorted(dedup, key=lambda r: tuple(v or "" for v in r))

    con = sqlite3.connect(db_path)
    try:
        con.execute("DROP TABLE IF EXISTS org_function")
        con.executescript(_SCHEMA)
        con.executemany(
            "INSERT INTO org_function(team, grp, part, function1, function2) VALUES (?,?,?,?,?)",
            rows,
        )
        con.commit()
    finally:
        con.close()
    return len(rows)


def list_source_columns(
    source_table: Optional[str] = None,
    env_file: Optional[str] = None,
) -> List[str]:
    """원본 테이블의 실제 열 이름 목록 조회 (columns 매핑 작성용).

    MySQL 의 SHOW COLUMNS / information_schema.columns 와 같은 정보를
    SQLAlchemy inspect 로 dialect 무관하게 가져온다.
    """
    load_dotenv(env_file, override=False)
    source_table = source_table or os.environ["SSOT_DB_TABLE"]
    engine = _source_engine(env_file)
    return [c["name"] for c in inspect(engine).get_columns(source_table)]


def get_org_functions(
    team: Optional[str] = None,
    group: Optional[str] = None,
    part: Optional[str] = None,
    db_path: str = DEFAULT_DB_PATH,
) -> Dict:
    """조직명으로 해당 조직(하위 포함)의 기능 목록(Function1+Function2 합집합)을 반환.

    team/group/part 는 각각 줄 수도, 생략할 수도 있다.
    예) team만 → 그 팀 전체 기능, group만 → 그 그룹 기능, team+group+part → 해당 파트 기능.

    Returns:
        {"query": {...}, "matched_rows": n, "functions": [정렬된 고유 기능 목록]}
    """
    filters = {"team": team, "grp": group, "part": part}
    where, params = [], []
    for col, val in filters.items():
        v = _norm(val)
        if v is not None:
            where.append(f"{col} = ?")
            params.append(v)
    if not where:
        raise ValueError("team/group/part 중 최소 하나는 지정해야 한다")

    sql = f"SELECT function1, function2 FROM org_function WHERE {' AND '.join(where)}"
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute(sql, params).fetchall()
    finally:
        con.close()

    funcs = {f for f1, f2 in rows for f in (f1, f2) if f}
    return {
        "query": {"team": team, "group": group, "part": part},
        "matched_rows": len(rows),
        "functions": sorted(funcs),
    }


def get_org_functions_by_name(name: str, db_path: str = DEFAULT_DB_PATH) -> Dict:
    """조직명 하나만 받아 팀/그룹/파트 어느 레벨인지 자동 판별해 기능 목록 반환.

    이름이 여러 레벨에 동시에 존재하면 매칭된 모든 라인의 기능 합집합.
    """
    n = _norm(name)
    if n is None:
        raise ValueError("조직명이 비어 있다")

    con = sqlite3.connect(db_path)
    try:
        rows = con.execute(
            "SELECT team, grp, part, function1, function2 FROM org_function "
            "WHERE team = ? OR grp = ? OR part = ?",
            (n, n, n),
        ).fetchall()
    finally:
        con.close()

    levels = sorted(
        {lvl for t, g, p, _, _ in rows for lvl, v in (("team", t), ("group", g), ("part", p)) if v == n}
    )
    funcs = {f for _, _, _, f1, f2 in rows for f in (f1, f2) if f}
    return {
        "query": {"org": name},
        "matched_levels": levels,
        "matched_rows": len(rows),
        "functions": sorted(funcs),
    }
