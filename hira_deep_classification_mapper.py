"""
HIRA 요양기관 업무포털 깊은 계층 색인분류 추출 크롤러
대분류 → 중분류 → 소분류의 전체 계층 구조를 완전히 탐색하여 세부 코드까지 추출
"""

import asyncio
import logging
import csv
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from playwright.async_api import async_playwright, Page, Browser, BrowserContext, Locator

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('hira_deep_classification.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class HIRADeepClassificationMapper:
    def __init__(self, output_dir: str = "./output"):
        """깊은 계층 색인분류 추출 크롤러 초기화"""
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        
        # HIRA 웹사이트 URL
        self.main_url = "https://biz.hira.or.kr/index.do"
        
        # 분류 데이터 저장
        self.classification_data: List[Dict] = []
        
        # Nexacro 세션 유지용 메인 페이지 참조
        self.main_page: Optional[Page] = None
        
    async def setup_browser(self) -> tuple[Browser, BrowserContext]:
        """브라우저 설정 및 컨텍스트 생성"""
        playwright = await async_playwright().start()
        
        browser = await playwright.chromium.launch(
            headless=False,
            slow_mo=1500,  # 더 느린 속도로 안정성 확보
            args=['--disable-web-security', '--disable-features=VizDisplayCompositor']
        )
        
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080}
        )
        
        return browser, context
        
    async def setup_main_page(self, context: BrowserContext) -> Page:
        """메인 페이지 설정 및 세션 확보"""
        try:
            logger.info(f"메인 페이지 접속: {self.main_url}")
            
            page = await context.new_page()
            await page.goto(self.main_url, wait_until='networkidle', timeout=30000)
            
            # Nexacro 애플리케이션 로딩 대기
            logger.info("Nexacro 메인 애플리케이션 로딩 대기...")
            await asyncio.sleep(10)
            
            # 심사기준 종합서비스 메뉴 찾기
            menu_link = page.locator('text=심사기준 종합서비스')
            if await menu_link.count() > 0:
                logger.info("메뉴 링크 발견: text=심사기준 종합서비스")
                
                # 새 페이지 열기 대기
                async with context.expect_page() as new_page_info:
                    await menu_link.click()
                
                popup_page = await new_page_info.value
                await popup_page.wait_for_load_state('networkidle', timeout=30000)
                
                logger.info("Nexacro 팝업 애플리케이션 로딩 대기...")
                await asyncio.sleep(10)
                logger.info("팝업 페이지 로딩 완료")
                
                self.main_page = page  # 세션 유지를 위해 메인 페이지 보관
                return popup_page
            else:
                logger.error("심사기준 종합서비스 메뉴를 찾을 수 없습니다.")
                return None
                
        except Exception as e:
            logger.error(f"메인 페이지 설정 실패: {e}")
            return None
    
    async def open_classification_modal(self, page: Page) -> bool:
        """색인분류검색 모달을 연다"""
        try:
            logger.info("색인분류검색 모달 열기 시도...")
            
            # DOM 완전 로딩 대기
            await asyncio.sleep(3)
            await page.wait_for_load_state('networkidle', timeout=10000)
            
            # 정확한 버튼 ID로 클릭
            exact_button_id = '#InfoBank_form_divMain_divWork1_btnIdxDiv'
            btn_element = page.locator(exact_button_id)
            
            if await btn_element.count() > 0:
                logger.info("색인분류검색 버튼 발견!")
                await btn_element.click()
                await asyncio.sleep(3)
                
                # 모달 열림 확인
                modal_check = '#InfoBank_RvStdInqIdxPL'
                if await page.locator(modal_check).count() > 0:
                    logger.info("색인분류검색 모달이 성공적으로 열렸습니다")
                    return True
            
            logger.error("색인분류검색 버튼을 찾을 수 없습니다")
            return False
            
        except Exception as e:
            logger.error(f"색인분류검색 모달 열기 실패: {e}")
            return False
    
    async def get_input_field_code(self, page: Page) -> str:
        """검색 입력 필드에서 자동 입력된 코드를 가져온다"""
        try:
            input_selector = '#InfoBank_form_divMain_divWork1_edtSearchTxt_input'
            search_input = page.locator(input_selector)
            
            if await search_input.is_visible():
                value = await search_input.input_value()
                return value.strip() if value else ""
        except Exception as e:
            logger.debug(f"입력 필드 코드 가져오기 실패: {e}")
        return ""
    
    async def extract_current_level_items(self, page: Page, level_name: str) -> List[Dict]:
        """현재 레벨의 고유한 분류 항목들을 추출한다"""
        try:
            logger.info(f"{level_name} 항목 추출 시작...")
            
            # 그리드 요소들 찾기
            tree_selector = '#InfoBank_RvStdInqIdxPL_form_grdIdxDiv1_body div[id*="gridrow"]:visible'
            elements = page.locator(tree_selector)
            count = await elements.count()
            
            if count == 0:
                logger.warning(f"{level_name} 항목을 찾을 수 없습니다.")
                return []
            
            logger.info(f"총 {count}개 요소 발견")
            
            # 고유한 텍스트만 추출 (중복 제거)
            unique_items = []
            seen_texts = set()
            
            for i in range(min(count, 50)):  # 최대 50개까지 확인
                try:
                    element = elements.nth(i)
                    if not await element.is_visible():
                        continue
                    
                    text = await element.text_content()
                    if not text or not text.strip():
                        continue
                    
                    text = text.strip()
                    
                    # 의미없는 텍스트 필터링
                    skip_patterns = ['분류명(분류코드)', '', ' ', '　']
                    if text in skip_patterns:
                        continue
                    
                    # 이미 본 텍스트는 건너뛰기
                    if text in seen_texts:
                        continue
                    
                    seen_texts.add(text)
                    
                    # 코드와 명칭 분리
                    code = ""
                    name = text
                    
                    # 괄호 안의 코드 추출 (예: "요양급여비용산정기준(행위)(A)")
                    paren_match = re.search(r'\\(([A-Z][0-9]*)\\)$', text)
                    if paren_match:
                        code = paren_match.group(1)
                        name = text[:paren_match.start()].strip()
                    else:
                        # 다른 패턴으로 코드 찾기
                        code_match = re.search(r'\\b([A-Z][0-9]*)\\b', text)
                        if code_match:
                            code = code_match.group(1)
                            name = re.sub(r'\\([A-Z][0-9]*\\)', '', text).strip()
                    
                    unique_items.append({
                        'text': text,
                        'code': code,
                        'name': name,
                        'element': element,
                        'index': i
                    })
                    
                    logger.debug(f"{level_name} 항목 추가: '{text}' (코드: {code})")
                    
                except Exception as e:
                    logger.debug(f"요소 {i} 처리 실패: {e}")
                    continue
            
            logger.info(f"{level_name} 고유 항목 {len(unique_items)}개 추출 완료")
            return unique_items
            
        except Exception as e:
            logger.error(f"{level_name} 항목 추출 실패: {e}")
            return []
    
    async def click_item_safely(self, element: Locator, item_name: str) -> bool:
        """안전하게 항목을 클릭한다"""
        try:
            # 1차: 일반 클릭
            await element.click(timeout=5000)
            return True
        except Exception as e:
            logger.warning(f"{item_name} 일반 클릭 실패, 강제 클릭 시도")
            try:
                # 2차: 강제 클릭
                await element.click(force=True, timeout=5000)
                return True
            except Exception as e2:
                logger.warning(f"{item_name} 강제 클릭도 실패, JavaScript 클릭 시도")
                try:
                    # 3차: JavaScript 클릭
                    await element.evaluate('element => element.click()')
                    return True
                except Exception as e3:
                    logger.error(f"{item_name} 모든 클릭 방법 실패: {e3}")
                    return False
    
    async def wait_for_content_update(self, page: Page, timeout_ms: int = 5000):
        """컨텐츠 업데이트를 기다린다"""
        try:
            # 네트워크 요청 완료 대기
            await page.wait_for_load_state('networkidle', timeout=timeout_ms)
            await asyncio.sleep(2)  # 추가 대기
        except Exception as e:
            logger.debug(f"컨텐츠 업데이트 대기 중 타임아웃: {e}")
            await asyncio.sleep(3)  # 기본 대기
    
    async def traverse_deep_classification_tree(self, page: Page):
        """깊은 계층 구조를 완전히 탐색한다"""
        try:
            logger.info("깊은 계층 색인분류 트리 순회 시작...")
            
            # 1단계: 대분류 목록 추출
            major_items = await self.extract_current_level_items(page, "대분류")
            
            if not major_items:
                logger.error("대분류 항목을 찾을 수 없습니다.")
                return
            
            logger.info(f"총 {len(major_items)}개 대분류 발견")
            
            # 각 대분류별로 순회
            for major_idx, major_item in enumerate(major_items):
                try:
                    major_code = major_item['code']
                    major_name = major_item['name']
                    major_text = major_item['text']
                    
                    logger.info(f"\\n=== [{major_idx+1}/{len(major_items)}] 대분류 처리: {major_text} ===")
                    
                    # 대분류 클릭
                    if not await self.click_item_safely(major_item['element'], f"대분류 {major_text}"):
                        continue
                    
                    await self.wait_for_content_update(page)
                    
                    # 2단계: 중분류 목록 추출
                    middle_items = await self.extract_current_level_items(page, "중분류")
                    
                    if not middle_items:
                        logger.warning(f"대분류 '{major_text}'에 중분류가 없습니다.")
                        # 대분류만 있는 경우도 저장
                        auto_code = await self.get_input_field_code(page)
                        self.classification_data.append({
                            '대분류코드': major_code,
                            '대분류명': major_name,
                            '중분류코드': '',
                            '중분류명': '',
                            '소분류코드': '',
                            '소분류명': '',
                            '자동입력코드': auto_code,
                            '전체텍스트': major_text
                        })
                        continue
                    
                    logger.info(f"  └ {len(middle_items)}개 중분류 발견")
                    
                    # 각 중분류별로 순회
                    for middle_idx, middle_item in enumerate(middle_items):
                        try:
                            middle_code = middle_item['code']
                            middle_name = middle_item['name']
                            middle_text = middle_item['text']
                            
                            logger.info(f"    [{middle_idx+1}/{len(middle_items)}] 중분류 처리: {middle_text}")
                            
                            # 중분류 클릭
                            if not await self.click_item_safely(middle_item['element'], f"중분류 {middle_text}"):
                                continue
                            
                            await self.wait_for_content_update(page)
                            
                            # 3단계: 소분류 목록 추출
                            minor_items = await self.extract_current_level_items(page, "소분류")
                            
                            if not minor_items:
                                logger.warning(f"중분류 '{middle_text}'에 소분류가 없습니다.")
                                # 중분류까지만 있는 경우도 저장
                                auto_code = await self.get_input_field_code(page)
                                self.classification_data.append({
                                    '대분류코드': major_code,
                                    '대분류명': major_name,
                                    '중분류코드': middle_code,
                                    '중분류명': middle_name,
                                    '소분류코드': '',
                                    '소분류명': '',
                                    '자동입력코드': auto_code,
                                    '전체텍스트': f"{major_text} > {middle_text}"
                                })
                                continue
                            
                            logger.info(f"      └ {len(minor_items)}개 소분류 발견")
                            
                            # 각 소분류별로 순회
                            for minor_idx, minor_item in enumerate(minor_items):
                                try:
                                    minor_code = minor_item['code']
                                    minor_name = minor_item['name']
                                    minor_text = minor_item['text']
                                    
                                    logger.info(f"        [{minor_idx+1}/{len(minor_items)}] 소분류 처리: {minor_text}")
                                    
                                    # 소분류 클릭
                                    if not await self.click_item_safely(minor_item['element'], f"소분류 {minor_text}"):
                                        continue
                                    
                                    await self.wait_for_content_update(page, 3000)  # 짧은 대기
                                    
                                    # 자동 입력된 코드 확인
                                    auto_code = await self.get_input_field_code(page)
                                    
                                    # 완전한 분류 데이터 저장
                                    classification_data = {
                                        '대분류코드': major_code,
                                        '대분류명': major_name,
                                        '중분류코드': middle_code,
                                        '중분류명': middle_name,
                                        '소분류코드': minor_code,
                                        '소분류명': minor_name,
                                        '자동입력코드': auto_code,
                                        '전체텍스트': f"{major_text} > {middle_text} > {minor_text}"
                                    }
                                    
                                    self.classification_data.append(classification_data)
                                    
                                    logger.info(f"          └ 저장: {auto_code or minor_code} - {minor_name}")
                                    
                                except Exception as e:
                                    logger.error(f"소분류 '{minor_text}' 처리 실패: {e}")
                                    continue
                                    
                        except Exception as e:
                            logger.error(f"중분류 '{middle_text}' 처리 실패: {e}")
                            continue
                            
                except Exception as e:
                    logger.error(f"대분류 '{major_text}' 처리 실패: {e}")
                    continue
            
            logger.info(f"\\n깊은 계층 순회 완료. 총 {len(self.classification_data)}개 항목 수집")
            
        except Exception as e:
            logger.error(f"깊은 계층 순회 중 오류: {e}")
    
    async def save_to_csv(self) -> str:
        """수집된 데이터를 CSV 파일로 저장한다"""
        try:
            if not self.classification_data:
                logger.warning("저장할 데이터가 없습니다.")
                return ""
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"hira_deep_classification_{timestamp}.csv"
            filepath = self.output_dir / filename
            
            with open(filepath, 'w', newline='', encoding='utf-8-sig') as csvfile:
                fieldnames = ['대분류코드', '대분류명', '중분류코드', '중분류명', '소분류코드', '소분류명', '자동입력코드', '전체텍스트']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                
                writer.writeheader()
                for data in self.classification_data:
                    writer.writerow(data)
            
            logger.info(f"CSV 파일 저장 완료: {filepath}")
            logger.info(f"총 {len(self.classification_data)}개 항목 저장")
            
            # 통계 출력
            levels = {'대분류만': 0, '중분류까지': 0, '소분류까지': 0}
            for item in self.classification_data:
                if not item['중분류코드']:
                    levels['대분류만'] += 1
                elif not item['소분류코드']:
                    levels['중분류까지'] += 1
                else:
                    levels['소분류까지'] += 1
            
            logger.info(f"수집 통계: {levels}")
            
            return str(filepath)
            
        except Exception as e:
            logger.error(f"CSV 저장 실패: {e}")
            return ""
    
    async def run(self):
        """메인 실행 함수"""
        browser = None
        try:
            logger.info("HIRA 깊은 계층 색인분류 추출 시작")
            
            # 브라우저 설정
            browser, context = await self.setup_browser()
            
            # 메인 페이지 설정 및 팝업 페이지 열기
            popup_page = await self.setup_main_page(context)
            if not popup_page:
                return
            
            # 색인분류검색 모달 열기
            if not await self.open_classification_modal(popup_page):
                return
            
            # 깊은 계층 구조 탐색
            await self.traverse_deep_classification_tree(popup_page)
            
            # CSV 파일 저장
            saved_file = await self.save_to_csv()
            if saved_file:
                logger.info(f"깊은 계층 분류 정보 저장 완료: {saved_file}")
            
        except Exception as e:
            logger.error(f"실행 중 오류 발생: {e}")
        
        finally:
            if browser:
                logger.info("브라우저 정리 완료")
                await browser.close()

async def main():
    """메인 함수"""
    mapper = HIRADeepClassificationMapper()
    await mapper.run()

if __name__ == "__main__":
    asyncio.run(main())