# HIRA 수가코드 자동화 크롤러 프로젝트

HIRA(건강보험심사평가원) 요양기관 업무포털에서 수가코드 정보를 자동으로 수집하는 Playwright 기반 크롤러 모음입니다.

## 📋 프로젝트 개요

HIRA 업무포털의 복잡한 Nexacro 기반 인터페이스를 자동화하여 수가코드 관련 데이터를 효율적으로 수집합니다. 
직접 검색 입력이 불가능한 색인분류 검색 시스템을 마우스 클릭으로 탐색하여 모든 수가코드 정보를 다운로드할 수 있습니다.

## 🚀 주요 기능

### 1. 기본 수가코드 크롤러 (`hira_crawler.py`)
- 사전 준비된 수가코드 목록을 기반으로 개별 검색
- 각 수가코드별 엑셀 파일 다운로드
- Nexacro 세션 의존성 처리

### 2. 색인분류 기반 크롤러 (`hira_classification_crawler.py`)
- 수가코드-분류경로 매핑을 통한 정확한 검색
- 대분류 → 중분류 → 소분류 순차 클릭 탐색
- 분류 경로 기반 자동 수가코드 입력

### 3. 전체 트리 탐색 크롤러 (`hira_full_tree_crawler.py`)
- 사전 수가코드 목록 없이 색인분류 트리 완전 탐색
- 재귀적 트리 탐색으로 모든 분류 경로 자동 발견
- 백트래킹 기능으로 전체 분류 체계 완전 수집

## 🛠 시스템 요구사항

- Python 3.8+
- Windows 10/11 (Playwright Chromium 지원)
- 최소 8GB RAM (브라우저 자동화용)
- 안정적인 인터넷 연결

## ⚙️ 설치 및 설정

### 1. 환경 설정
```bash
# 가상환경 생성 (권장)
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/Mac

# 필수 패키지 설치
pip install -r requirements.txt

# Playwright 브라우저 설치
playwright install chromium
```

### 2. MCP 서버 설정 (선택사항)
```bash
# Claude MCP Playwright 서버 추가
claude mcp add playwright npx @playwright/mcp@latest
```

## 📁 프로젝트 구조

```
cg_suri_playwright/
├── README.md                           # 프로젝트 설명서
├── requirements.txt                    # Python 의존성
├── hira_crawler.py                     # 기본 크롤러
├── hira_classification_crawler.py      # 색인분류 크롤러
├── hira_full_tree_crawler.py          # 전체 트리 탐색 크롤러
├── 수가코드목록_1.xlsx                 # 수가코드 목록 (사용자 제공)
├── 수가코드_분류매핑.xlsx              # 분류 매핑 (사용자 제공)
├── downloads/                          # 다운로드된 파일 저장소
├── work_logs/                          # 작업 내역 기록
└── *.log                              # 실행 로그 파일
```

## 🔧 구동 방법

### 방법 1: 기본 수가코드 크롤러
수가코드 목록이 준비되어 있을 때 사용합니다.

```bash
# 수가코드목록_1.xlsx 파일을 프로젝트 루트에 배치
python hira_crawler.py
```

**필요한 파일:**
- `수가코드목록_1.xlsx`: 첫 번째 컬럼에 수가코드 나열

### 방법 2: 색인분류 기반 크롤러
수가코드와 분류 경로 매핑이 있을 때 사용합니다.

```bash
# 필요한 엑셀 파일들을 준비 후 실행
python hira_classification_crawler.py
```

**필요한 파일:**
- `수가코드목록_1.xlsx`: 수가코드 목록
- `수가코드_분류매핑.xlsx`: 코드별 분류 경로 (대분류, 중분류, 소분류)

### 방법 3: 전체 트리 탐색 크롤러 (권장)
사전 준비 없이 모든 수가코드를 자동 수집할 때 사용합니다.

```bash
# 별도 준비 파일 없이 바로 실행 가능
python hira_full_tree_crawler.py
```

**특징:**
- 사전 수가코드 목록 불필요
- 색인분류 트리를 완전히 탐색하여 모든 분류 발견
- 각 소분류별 수가코드 자동 다운로드

## 📊 출력 결과

### 다운로드 파일
- `downloads/` 폴더에 엑셀 파일들 저장
- 파일명: `{수가코드}_{타임스탬프}_{원본파일명}.xlsx`
- 분류별 파일명: `{대분류}_{중분류}_{소분류}_{타임스탬프}.xlsx`

### 결과 보고서
- `*_crawling_results_YYYYMMDD_HHMMSS.csv`: 처리 결과 요약
- `collected_paths_YYYYMMDD_HHMMSS.txt`: 수집된 분류 경로 목록
- `*.log`: 상세 실행 로그

## 🔍 주요 특징

### Nexacro 호환성
- Nexacro 플랫폼의 특수한 UI 구조 처리
- 세션 의존성 관리 (메인 페이지 유지)
- 비동기 로딩 대기 처리

### 안정성
- 페이지 닫힘 감지 및 자동 재접속
- 다양한 CSS 선택자로 요소 탐지
- 예외 상황별 상세한 오류 처리

### 디버깅 지원
- 실시간 로그 출력
- 페이지 요소 분석 기능
- GUI 모드로 동작 과정 시각적 확인

## ⚠️ 주의사항

1. **속도 제한**: 서버 부하 방지를 위해 적절한 대기 시간 설정
2. **네트워크 상태**: 안정적인 인터넷 연결 필요
3. **세션 관리**: Nexacro 특성상 브라우저 창을 임의로 닫지 마세요
4. **파일 권한**: downloads 폴더 쓰기 권한 확인

## 🐛 문제 해결

### 자주 발생하는 문제

1. **색인분류 버튼을 찾을 수 없음**
   ```bash
   # 페이지 로딩 시간을 늘려보세요
   await asyncio.sleep(15)  # 10초에서 15초로 증가
   ```

2. **다운로드 실패**
   - downloads 폴더 권한 확인
   - 디스크 용량 확인
   - 방화벽/백신 프로그램 확인

3. **브라우저 크래시**
   - 메모리 부족: 다른 프로그램 종료
   - Chromium 재설치: `playwright install chromium`

## 📞 지원

- 로그 파일을 확인하여 오류 원인 파악
- GUI 모드로 실행하여 동작 과정 직접 확인
- 이슈 발생 시 로그 파일과 함께 문의

## 📄 라이선스

이 프로젝트는 개인 및 연구 목적으로 자유롭게 사용할 수 있습니다.
상업적 이용 시에는 HIRA 이용약관을 준수해야 합니다.