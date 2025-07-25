"""
HIRA 요양기관 업무포털 상세 색인분류 추출 크롤러
사용자가 원하는 형태로 데이터 추출: A00000: 산정방법 및 일반원칙
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
        logging.FileHandler('hira_classification_detailed.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class HIRADetailedClassificationMapper:
    def __init__(self, output_dir: str = "./output"):
        """상세 색인분류 추출 크롤러 초기화"""
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
            slow_mo=1000,  # 동작 간 1초 대기
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
    
    async def extract_detailed_classification_item(self, page: Page, element: Locator, level: str) -> Optional[Dict]:
        """개별 분류 항목을 클릭하여 상세 정보를 추출한다"""
        try:
            # 항목 텍스트 가져오기
            text = await element.text_content()
            if not text:
                return None
            
            text = text.strip()
            logger.info(f"{level} 항목 상세 분석 시작: '{text}'")
            
            # 항목 클릭 전 입력 필드 상태 확인
            before_click_code = await self.get_input_field_code(page)
            
            # 항목 클릭 (여러 방법 시도)
            try:
                await element.click()
            except Exception as e:
                logger.warning(f"일반 클릭 실패, 강제 클릭 시도: {e}")
                try:
                    await element.click(force=True)
                except Exception as e2:
                    logger.warning(f"강제 클릭도 실패, JavaScript 클릭 시도: {e2}")
                    await element.evaluate('element => element.click()')
            
            await asyncio.sleep(2)  # 화면 업데이트 대기
            
            # 클릭 후 입력 필드에서 자동 입력된 코드 확인
            after_click_code = await self.get_input_field_code(page)
            
            # 코드와 명칭 분리
            code = ""
            name = text
            
            # 패턴 1: 텍스트에서 괄호 안의 코드 추출 (예: "요양급여비용산정기준(행위)(A)")
            paren_match = re.search(r'\\(([A-Z][0-9]*)\\)$', text)
            if paren_match:
                code = paren_match.group(1)
                name = text[:paren_match.start()].strip()
            else:
                # 패턴 2: 단순 영문 코드 찾기
                code_match = re.search(r'[A-Z][0-9]*', text)
                if code_match:
                    code = code_match.group(0)
                    # 코드를 제외한 부분을 명칭으로
                    name = re.sub(r'\\([A-Z][0-9]*\\)', '', text).strip()
            
            # 자동 입력된 코드가 더 상세하다면 사용
            if after_click_code and after_click_code != before_click_code:
                detailed_code = after_click_code
                logger.info(f"자동 입력된 상세 코드 발견: {detailed_code}")
            else:
                detailed_code = code
            
            result = {
                'level': level,
                'text': text,
                'code': code,
                'detailed_code': detailed_code,
                'name': name,
                'before_click_code': before_click_code,
                'after_click_code': after_click_code
            }
            
            logger.info(f"추출 완료 - 코드: {code}, 상세코드: {detailed_code}, 명칭: {name}")
            return result
            
        except Exception as e:
            logger.error(f"{level} 항목 상세 분석 실패: {e}")
            return None
    
    async def traverse_classification_tree_detailed(self, page: Page):
        """색인분류 트리를 순회하며 상세 정보를 추출한다"""
        try:
            logger.info("상세 색인분류 트리 순회 시작...")
            
            # 1단계: 대분류 목록 추출
            tree_selector = '#InfoBank_RvStdInqIdxPL_form_grdIdxDiv1_body div[id*="gridrow"]:visible'
            elements = page.locator(tree_selector)
            count = await elements.count()
            
            if count == 0:
                logger.error("분류 항목을 찾을 수 없습니다.")
                return
            
            logger.info(f"총 {count}개 분류 항목 발견")
            
            # 고유한 텍스트만 추출 (중복 제거)
            unique_items = []
            seen_texts = set()
            
            for i in range(min(count, 30)):  # 최대 30개까지
                try:
                    element = elements.nth(i)
                    if not await element.is_visible():
                        continue
                    
                    text = await element.text_content()
                    if not text or text.strip() in seen_texts:
                        continue
                    
                    text = text.strip()
                    seen_texts.add(text)
                    unique_items.append((text, element))
                    
                except Exception as e:
                    continue
            
            logger.info(f"고유한 분류 항목 {len(unique_items)}개 추출")
            
            # 각 항목에 대해 상세 분석
            for idx, (text, element) in enumerate(unique_items):
                try:
                    logger.info(f"[{idx+1}/{len(unique_items)}] 분류 항목 분석: {text}")
                    
                    # 상세 정보 추출
                    detail_info = await self.extract_detailed_classification_item(page, element, "분류")
                    
                    if detail_info:
                        # 데이터 저장
                        classification_data = {
                            '분류레벨': detail_info['level'],
                            '분류텍스트': detail_info['text'],
                            '기본코드': detail_info['code'],
                            '상세코드': detail_info['detailed_code'],
                            '분류명': detail_info['name'],
                            '클릭전코드': detail_info['before_click_code'],
                            '클릭후코드': detail_info['after_click_code']
                        }
                        
                        self.classification_data.append(classification_data)
                        logger.info(f"저장: {detail_info['detailed_code']} - {detail_info['name']}")
                
                except Exception as e:
                    logger.error(f"분류 항목 '{text}' 처리 실패: {e}")
                    continue
            
            logger.info(f"상세 분류 정보 수집 완료. 총 {len(self.classification_data)}개 항목")
            
        except Exception as e:
            logger.error(f"상세 트리 순회 중 오류: {e}")
    
    async def save_to_csv(self) -> str:
        """수집된 데이터를 CSV 파일로 저장한다"""
        try:
            if not self.classification_data:
                logger.warning("저장할 데이터가 없습니다.")
                return ""
            
            # 현재 시간을 파일명에 포함
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"hira_detailed_classification_{timestamp}.csv"
            filepath = self.output_dir / filename
            
            # CSV 파일 작성
            with open(filepath, 'w', newline='', encoding='utf-8-sig') as csvfile:
                fieldnames = ['분류레벨', '분류텍스트', '기본코드', '상세코드', '분류명', '클릭전코드', '클릭후코드']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                
                writer.writeheader()
                for data in self.classification_data:
                    writer.writerow(data)
            
            logger.info(f"CSV 파일 저장 완료: {filepath}")
            logger.info(f"총 {len(self.classification_data)}개 항목 저장")
            
            return str(filepath)
            
        except Exception as e:
            logger.error(f"CSV 저장 실패: {e}")
            return ""
    
    async def run(self):
        """메인 실행 함수"""
        browser = None
        try:
            logger.info("HIRA 상세 색인분류 추출 시작")
            
            # 브라우저 설정
            browser, context = await self.setup_browser()
            
            # 메인 페이지 설정 및 팝업 페이지 열기
            popup_page = await self.setup_main_page(context)
            if not popup_page:
                return
            
            # 색인분류검색 모달 열기
            if not await self.open_classification_modal(popup_page):
                return
            
            # 상세 분류 정보 추출
            await self.traverse_classification_tree_detailed(popup_page)
            
            # CSV 파일 저장
            saved_file = await self.save_to_csv()
            if saved_file:
                logger.info(f"상세 분류 정보 저장 완료: {saved_file}")
            
        except Exception as e:
            logger.error(f"실행 중 오류 발생: {e}")
        
        finally:
            if browser:
                logger.info("브라우저 정리 완료")
                await browser.close()

async def main():
    """메인 함수"""
    mapper = HIRADetailedClassificationMapper()
    await mapper.run()

if __name__ == "__main__":
    asyncio.run(main())