# 유지관리자 문서

## 구조
```
insa_tongji/
  core/        UI·한컴과 독립된 순수 로직
    excel_reader  헤더 매핑(열 이름 기준), 주민번호 열 미사용
    normalizer    NFKC·제로폭/방향 제어 문자 제거, 날짜 해석
    validator     V01~V15, 발령일 우선순위
    school_matcher S1~S5 학교명 매칭, 지역 접두어 자동 감지
    josa          로/으로
    template_registry 양식 점검(매직넘버·zip 안전·필드 스캔)
    hwpx_engine   HWPX XML 텍스트 치환 (Track A)
    hwp_com       한컴 COM (선택: HWP 변환·PDF·열기 확인)
    verifier      생성 후 파일별 검증 C1~C5
    generator     건별 격리 생성
    packager      파일명·ZIP·처리결과/오류목록 엑셀
  app/         로컬 웹 서버(표준 라이브러리 http.server)·세션·UI(static)
tools/         build_dist.py, check_dist.py, smoke_exe.py
tests/         pytest (한컴 필요 테스트는 -m hancom)
```

## 개발 명령
```
python -m ruff check insa_tongji tests
python -m pytest -q                 # 한컴 불필요 테스트
python -m pytest -q -m hancom       # 한컴 설치 PC에서 열기·1쪽·HWP 변환 검증
python tools/build_dist.py          # dist/인사발령장 자동생성기-YYYYMMDD-vX.Y.Z (폴더·zip·sha256) 빌드 + 청결 검사 + 스모크
python -m insa_tongji               # 개발 중 직접 실행
```
의존성: Python 3.11+, openpyxl, lxml(테스트), pywin32(한컴 연동, 선택), PyInstaller(빌드).

## 검증 규칙을 바꿀 때
- 학교명 자동 확정 규칙(`school_matcher`)과 날짜 규칙(`validator`)은 **인사 업무 결과에 직접 영향**을 줍니다. 변경 시 `tests/test_core_data.py`의 경계 사례(범용 급 단어, 괄호, 숫자 날짜)를 반드시 통과해야 합니다.
- 학교 약칭 충돌은 시작 시 검사해 화면 사전점검에 표시합니다(`SchoolMatcher.collisions`).

## 양식이 바뀔 때
양식의 `{{…}}`는 `직종·성명·발령일·현임교·발령교` 5종만 허용합니다. 새 필드가 필요하면 `hwpx_engine.ALLOWED_FIELDS`, `validator.Person.values`, `REQUIRED`와 테스트를 함께 수정합니다.

## 장애 대응
| 증상 | 확인 |
|---|---|
| "허용되지 않는 필드가 있습니다" | 양식의 `{{ }}` 오타·띄어쓰기. 한컴에서 필드가 줄바꿈·표로 끊기지 않았는지 |
| "{{ }} 짝이 맞지 않거나 끊긴 필드" | 필드 문자열 중간에 서식·줄바꿈이 끼어 있음 → 한컴에서 필드를 지우고 다시 입력 |
| HWP 등록 실패 | 한컴 미설치/보안 창 대기. HWPX로 저장해 등록 |
| 생성 FAIL(C2~C5) | 처리결과.xlsx의 비고 열 코드 확인(아래) |

사후검증 코드: C1 ZIP/mimetype, C2 `{{` 잔존, C3 기대값 없음, C4 비텍스트 파트 변경, C5 본문 구조 변경.

## 알려진 한계
- `hwp_com`은 한컴 보안모듈이 없을 때 확인 창에서 대기할 수 있습니다(변환에는 120초 제한을 두었으나 한컴 프로세스가 남을 수 있음)(한컴 PC에서만 사용되는 선택 기능).
- 정밀한 렌더 비교는 한컴으로 직접 확인해야 합니다. 자동 검증은 구조·해시 비교입니다.

## 결과물 이름·버전
- 이름 규칙: `인사발령장 자동생성기-YYYYMMDD-vX.Y.Z` (폴더, `.zip`, `.zip.sha256.txt`).
- 버전은 `insa_tongji/__init__.py`의 `__version__` 한 곳이 기준이며, `pyproject.toml`·`docs/CHANGELOG.md` 첫 항목과 같아야 합니다(`tests/test_release.py`가 검사).
- 릴리스 절차: 버전 올림 → CHANGELOG 갱신 → ruff·pytest → `python tools/build_dist.py`.
