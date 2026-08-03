# -*- coding: utf-8 -*-
"""org-function REST API.

실행:
    uvicorn api:app --host 0.0.0.0 --port 8000   (org-function 폴더에서)

엔드포인트:
    GET  /columns                원본 테이블의 실제 열 이름 목록 (columns 매핑 작성용)
    POST /build                  원본 SSOT DB → 로컬 조직기능 DB 재구축
    GET  /functions              team/group/part 쿼리파라미터로 기능 목록
    GET  /functions/{org_name}   조직명 하나로 레벨 자동판별 조회
"""

from typing import Dict, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from core import (
    DEFAULT_DB_PATH,
    build_org_function_db,
    get_org_functions,
    get_org_functions_by_name,
    list_source_columns,
)

app = FastAPI(title="org-function API", version="1.0.0")


class BuildRequest(BaseModel):
    source_table: Optional[str] = None
    # 논리 역할 → 원본 테이블의 실제 열 이름 (GET /columns 로 확인 가능)
    # 예: {"team": "팀", "group": "그룹", "part": "파트",
    #      "function1": "Function1", "function2": "Function2"}
    columns: Optional[Dict[str, str]] = None
    db_path: str = DEFAULT_DB_PATH


@app.get("/columns")
def columns(table: Optional[str] = None):
    try:
        return {"table": table, "columns": list_source_columns(table)}
    except KeyError as e:
        raise HTTPException(status_code=400, detail=f"환경변수 누락: {e}")


@app.post("/build")
def build(req: BuildRequest):
    try:
        n = build_org_function_db(req.source_table, req.columns, req.db_path)
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "ok", "rows": n, "db_path": req.db_path}


@app.get("/functions")
def functions(
    team: Optional[str] = None,
    group: Optional[str] = None,
    part: Optional[str] = None,
):
    try:
        return get_org_functions(team=team, group=group, part=part)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/functions/{org_name}")
def functions_by_name(org_name: str):
    result = get_org_functions_by_name(org_name)
    if result["matched_rows"] == 0:
        raise HTTPException(status_code=404, detail=f"조직 없음: {org_name}")
    return result
