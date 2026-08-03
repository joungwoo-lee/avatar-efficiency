# org-function — 조직별 기능(Function) 조회 모듈

원본 SSOT DB(여러 열·다수 행)에서 **팀 / 그룹 / 파트 / Function1 / Function2** 열만 추출·중복제거·정렬해
로컬 조직기능 DB(SQLite)를 만들고, 조직명을 쿼리하면 해당 조직이 수행하는 기능 목록(Function1+Function2)을 반환한다.

> **열 지정 방식**: MySQL 등 RDB는 스프레드시트와 달리 1행 값이 라벨이 아니다 —
> 열 이름은 테이블 **스키마**에 정의되어 있다. 따라서 `columns` 매핑에는 원본 테이블의
> **실제 열 이름**을 넣는다. 열 이름을 모르면 `list_source_columns()` 또는 `GET /columns`로
> 조회하면 된다 (`SHOW COLUMNS FROM ...`와 동일 정보). 지정한 열이 스키마에 없으면
> 빌드가 실제 열 목록을 담은 에러로 즉시 실패한다.

## 구성

| 파일 | 역할 |
|---|---|
| `core.py` | 핵심 함수 2개: `build_org_function_db()`, `get_org_functions()` (+ `get_org_functions_by_name()`, `list_source_columns()`) |
| `api.py` | FastAPI REST API (`/columns`, `/build`, `/functions`) |
| `.env.example` | DB 접속·열 라벨 설정 예시 → `.env`로 복사해 사용 |
| `requirements.txt` | 의존성 |

## 동작 원리

1. **빌드** — `build_org_function_db()`
   - `.env`의 `SSOT_DB_*`로 원본 DB 접속 (`SSOT_DB_IP/PORT/DBNAME/ID/PW`, dialect는 `SSOT_DB_DIALECT`).
   - 팀/그룹/파트/Function1/Function2 에 해당하는 **원본 테이블 열 이름**을 지정받아 스키마 검증 후 그 5열만 SELECT.
   - 5열이 **모두 동일한 중복 라인 소거** 후 조직(팀→그룹→파트) 순으로 **정렬**하여 `org_functions.sqlite`의 `org_function` 테이블에 적재. 팀/그룹/파트 각각 인덱스 생성.
2. **조회** — `get_org_functions()`
   - `team`, `group`, `part` 중 **주어진 것만** AND 조건으로 필터. 팀 레벨 질문이면 team만, 파트 레벨이면 part만(또는 조합) 주면 된다 — 하위 조직의 기능이 모두 합쳐져 반환된다.
   - 매칭된 라인들의 Function1+Function2를 합집합·중복제거·정렬해 반환.
   - `get_org_functions_by_name("이름")`은 이름 하나로 팀/그룹/파트 어느 레벨인지 자동 판별해 조회.

## 사용법

```bash
cd org-function
pip install -r requirements.txt
cp .env.example .env   # 실제 접속정보·테이블·열 라벨로 수정
```

### 함수로 사용

```python
from core import build_org_function_db, get_org_functions, get_org_functions_by_name, list_source_columns

# 0) 원본 테이블의 실제 열 이름 확인 (columns 매핑 작성용)
print(list_source_columns("org_master"))
# 예: ['사번', '팀', '그룹', '파트', 'Function1', 'Function2', ...]

# 1) 조직기능 DB 구축 (columns 값 = 위에서 확인한 실제 열 이름)
n = build_org_function_db(
    source_table="org_master",
    columns={"team": "팀", "group": "그룹", "part": "파트",
             "function1": "Function1", "function2": "Function2"},
)
print(f"{n} rows loaded")

# 2) 조회 — 레벨별로 주어진 것만 지정
get_org_functions(team="플랫폼팀")                       # 팀 전체 기능
get_org_functions(group="인프라그룹")                     # 그룹 기능
get_org_functions(team="플랫폼팀", group="인프라그룹", part="네트워크파트")

# 3) 조직명 하나로 자동 판별
get_org_functions_by_name("인프라그룹")
```

반환 예:

```json
{
  "query": {"team": "플랫폼팀", "group": null, "part": null},
  "matched_rows": 12,
  "functions": ["네트워크 운영", "서버 구축", "모니터링", "..."]
}
```

### API로 사용

```bash
uvicorn api:app --host 0.0.0.0 --port 8000
```

```bash
# 원본 테이블 열 이름 확인
curl "localhost:8000/columns?table=org_master"

# DB 재구축 (columns 생략 시 .env의 SSOT_COL_* 사용)
curl -X POST localhost:8000/build -H "Content-Type: application/json" \
  -d '{"source_table": "org_master"}'

# 레벨별 조회 (team/group/part 임의 조합)
curl "localhost:8000/functions?team=플랫폼팀"
curl "localhost:8000/functions?group=인프라그룹&part=네트워크파트"

# 조직명 하나로 조회 (레벨 자동 판별)
curl "localhost:8000/functions/인프라그룹"
```

## 설정 레퍼런스 (.env)

| 키 | 필수 | 설명 |
|---|---|---|
| `SSOT_DB_IP` / `SSOT_DB_PORT` | ✅ | 원본 DB 호스트/포트 |
| `SSOT_DB_DBNAME` | ✅ | 데이터베이스명 (예: `dw_ods`) |
| `SSOT_DB_ID` / `SSOT_DB_PW` | ✅ | 접속 계정 |
| `SSOT_DB_DIALECT` | | SQLAlchemy dialect. 기본 `mysql+pymysql`, PostgreSQL은 `postgresql+psycopg2` |
| `SSOT_DB_TABLE` | | 원본 테이블명 기본값 |
| `SSOT_COL_TEAM/GROUP/PART/FUNC1/FUNC2` | | 열 이름 기본값 (build 인자가 우선) |

## 주의

- `build_org_function_db()`는 호출할 때마다 `org_function` 테이블을 **전체 재생성**(DROP 후 재적재)한다. 원본 변경 시 재실행하면 된다.
- 빈 문자열/공백 셀은 `NULL` 취급. 동일 조직명이 여러 레벨에 존재하면 `get_org_functions_by_name()`은 매칭된 모든 라인의 기능 합집합을 반환하며 `matched_levels`로 어떤 레벨에 매칭됐는지 알려준다.
- `.env`는 커밋하지 말 것(접속 정보 포함). `.env.example`만 커밋한다.
