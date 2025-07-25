"""
HIRA 요양기관 업무포털 색인분류 계층 구조 추출 크롤러
대분류 → 중분류 → 소분류의 전체 계층 구조를 순회하며 코드와 명칭을 추출하여 CSV로 저장
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
        logging.FileHandler('hira_classification_mapper.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class HIRAClassificationMapper:
    def __init__(self, output_dir: str = "./output"):
        """
        색인분류 계층 구조 추출 크롤러 초기화
        
        Args:
            output_dir: 출력 파일 저장 디렉토리
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        
        # HIRA 웹사이트 URL
        self.main_url = "https://biz.hira.or.kr/index.do"
        self.popup_url = "https://biz.hira.or.kr/popup.ndo?formname=qya_bizcom%3A%3AInfoBank.xfdl&framename=InfoBank"
        
        # CSS 선택자
        self.selectors = {
            'classification_search_btn': 'text=색인분류검색',
            'search_input': '#InfoBank_form_divMain_divWork1_edtSearchTxt_input',
            'modal_close_btn': 'text=닫기'
        }
        
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
        
    async def debug_modal_elements(self, page: Page, modal_title: str = ""):
        """모달 내부 요소들을 디버깅용으로 출력"""
        try:
            logger.info(f"=== {modal_title} 모달 요소 분석 시작 ===")
            
            # 모달 내 모든 클릭 가능한 요소 찾기
            modal_elements = await page.locator('div, span, td, li, a, button').all()
            
            tree_elements = []
            for i, element in enumerate(modal_elements[:50]):  # 처음 50개만 분석
                try:
                    text = await element.text_content()
                    if text and text.strip() and len(text.strip()) < 100:  # 너무 긴 텍스트 제외
                        tag_name = await element.evaluate('el => el.tagName')
                        classes = await element.get_attribute('class') or ''
                        
                        # 트리 구조나 리스트 요소로 보이는 것들 필터링
                        tree_keywords = ['tree', 'node', 'list', 'item', 'row', 'cell']
                        if any(keyword in classes.lower() for keyword in tree_keywords) or \
                           tag_name.lower() in ['li', 'td', 'span']:
                            tree_elements.append({
                                'index': i,
                                'tag': tag_name,
                                'text': text.strip()[:50],
                                'class': classes[:50]
                            })
                            
                except Exception as e:
                    continue
            
            logger.info(f"트리 구조 후보 요소 {len(tree_elements)}개 발견")
            for elem in tree_elements[:20]:  # 상위 20개만 출력
                logger.info(f"[{elem['index']}] {elem['tag']} - '{elem['text']}' (class: {elem['class']})")
                
            logger.info(f"=== {modal_title} 모달 요소 분석 완료 ===")
            
        except Exception as e:
            logger.error(f"모달 요소 분석 실패: {e}")
    
    async def open_main_page(self, context: BrowserContext) -> Page:
        """메인 페이지를 열고 Nexacro 세션을 확보한다"""
        try:
            if self.main_page is None or self.main_page.is_closed():
                logger.info(f"메인 페이지 접속: {self.main_url}")
                self.main_page = await context.new_page()
                await self.main_page.goto(self.main_url, wait_until='networkidle', timeout=30000)
                
                # Nexacro 애플리케이션 로딩 대기
                logger.info("Nexacro 메인 애플리케이션 로딩 대기...")
                await asyncio.sleep(10)
                
                logger.info("메인 페이지 로딩 완료 - 세션 확보")
            
            return self.main_page
            
        except Exception as e:
            logger.error(f"메인 페이지 열기 실패: {e}")
            raise
    
    async def open_popup_page(self, context: BrowserContext) -> Page:
        """메인 페이지에서 팝업을 열거나 직접 팝업 페이지에 접속한다"""
        try:
            # 방법 1: 메인 페이지에서 팝업 링크 찾기
            main_page = await self.open_main_page(context)
            
            # 심사기준 종합서비스 또는 InfoBank 메뉴 찾기
            menu_selectors = [
                "text=심사기준 종합서비스",
                "text=InfoBank",
                "a[href*='InfoBank']",
                "[onclick*='InfoBank']",
                "text=수가코드",
                "text=요양급여"
            ]
            
            popup_page = None
            for selector in menu_selectors:
                try:
                    menu_link = main_page.locator(selector).first
                    if await menu_link.is_visible():
                        logger.info(f"메뉴 링크 발견: {selector}")
                        
                        # 팝업이 열릴 것을 기대
                        async with context.expect_page() as popup_info:
                            await menu_link.click()
                            
                        popup_page = await popup_info.value
                        await popup_page.wait_for_load_state('networkidle', timeout=30000)
                        logger.info("메뉴에서 팝업 열기 성공")
                        break
                        
                except Exception as e:
                    logger.debug(f"메뉴 선택자 {selector} 시도 실패: {e}")
                    continue
            
            # 방법 2: 직접 팝업 URL 접속 (메인 페이지 referer 설정)
            if popup_page is None:
                logger.info("메뉴에서 팝업 열기 실패, 직접 팝업 URL로 접속")
                popup_page = await context.new_page()
                
                # referer를 메인 페이지로 설정하여 팝업 URL 접속
                await popup_page.goto(
                    self.popup_url, 
                    wait_until='networkidle', 
                    timeout=30000,
                    referer=self.main_url
                )
            
            # 팝업 페이지 로딩 대기
            logger.info("Nexacro 팝업 애플리케이션 로딩 대기...")
            await asyncio.sleep(10)
            
            # 기본 검색 입력창이 나타날 때까지 대기하여 팝업 로딩 확인
            try:
                search_input = popup_page.locator(self.selectors['search_input'])
                await search_input.wait_for(state='visible', timeout=20000)
                logger.info("팝업 페이지 로딩 완료")
            except:
                logger.warning("기본 검색 입력창을 찾을 수 없음. 계속 진행...")
            
            await asyncio.sleep(3)
            return popup_page
            
        except Exception as e:
            logger.error(f"팝업 페이지 열기 실패: {e}")
            raise
    
    async def ensure_popup_page(self, context: BrowserContext, popup_page: Optional[Page] = None) -> Page:
        """팝업 페이지가 닫혔는지 확인하거나 새로 열기"""
        if popup_page is not None and not popup_page.is_closed():
            return popup_page
            
        if popup_page is not None and popup_page.is_closed():
            logger.warning("팝업 페이지가 닫혔습니다. 재접속을 시도합니다.")
            
        return await self.open_popup_page(context)
    
    async def analyze_clickable_elements(self, page: Page):
        """페이지의 모든 클릭 가능한 요소를 분석하여 색인분류 버튼 후보를 찾는다"""
        try:
            logger.info("DOM 전체 분석으로 색인분류 버튼 후보 탐색...")
            
            # 클릭 가능한 모든 요소 수집
            clickable_selectors = [
                'div[style*="cursor: pointer"]',
                'div[tabindex]',
                'button',
                'input[type="button"]',
                'span[style*="cursor: pointer"]',
                'div[onclick]',
                'span[onclick]'
            ]
            
            candidates = []
            
            for selector in clickable_selectors:
                try:
                    elements = page.locator(selector)
                    count = await elements.count()
                    
                    for i in range(min(count, 20)):  # 최대 20개까지만 분석
                        try:
                            element = elements.nth(i)
                            
                            if not await element.is_visible():
                                continue
                            
                            # 요소의 텍스트 내용 확인
                            text = await element.text_content()
                            inner_html = await element.inner_html()
                            
                            # 색인분류 관련 키워드가 있는지 확인
                            if text and any(keyword in text for keyword in ['색인', '분류', '검색']):
                                candidates.append({
                                    'selector': selector,
                                    'index': i,
                                    'text': text.strip()[:50] if text else '',
                                    'html': inner_html[:100] if inner_html else ''
                                })
                            
                        except Exception as e:
                            continue
                            
                except Exception as e:
                    continue
            
            # 후보 요소들을 로그로 출력
            if candidates:
                logger.info(f"색인분류 버튼 후보 {len(candidates)}개 발견:")
                for i, candidate in enumerate(candidates[:10]):  # 상위 10개만 출력
                    logger.info(f"  [{i+1}] {candidate['selector']}[{candidate['index']}]: '{candidate['text']}'")
            else:
                logger.warning("색인분류 관련 텍스트를 포함한 클릭 가능한 요소를 찾을 수 없습니다.")
                
        except Exception as e:
            logger.error(f"DOM 분석 중 오류: {e}")
    
    async def verify_modal_opened(self, page: Page) -> bool:
        """색인분류검색 모달이 열렸는지 확인한다"""
        try:
            # 실제 modal_div.html 구조 기반 모달 감지
            modal_indicators = [
                '#InfoBank_RvStdInqIdxPL',  # 실제 모달 ID
                'div[id*="RvStdInqIdxPL"]',
                'div[style*="z-index: 1000002"]',  # 모달 z-index
                'div:has-text("대분류")',  # 모달 내부 "대분류" 텍스트
                'div[id*="grdIdxDiv1"]',  # 분류 그리드
                'div[class*="modal"]',
                'div[class*="popup"]', 
                'div[class*="dialog"]'
            ]
            
            for modal_sel in modal_indicators:
                if await page.locator(modal_sel).count() > 0:
                    logger.info(f"색인분류검색 모달이 성공적으로 열렸습니다: {modal_sel}")
                    return True
            
            logger.warning("모달이 열리지 않았습니다.")
            await self.debug_modal_elements(page, "색인분류")
            return False
            
        except Exception as e:
            logger.error(f"모달 확인 중 오류: {e}")
            return False
    
    async def open_classification_modal(self, page: Page) -> bool:
        """색인분류검색 모달을 연다"""
        try:
            logger.info("색인분류검색 모달 열기 시도...")
            
            # 모달이 이미 열려있는지 확인 (modal_div.html에서 발견된 구조)
            modal_check_selectors = [
                '#InfoBank_RvStdInqIdxPL',  # 실제 modal_div.html에서 발견된 모달 ID
                'div[id*="RvStdInqIdxPL"]',
                'div[style*="z-index: 1000002"]'  # 모달의 z-index 값
            ]
            
            for modal_sel in modal_check_selectors:
                if await page.locator(modal_sel).count() > 0:
                    logger.info("색인분류검색 모달이 이미 열려있습니다.")
                    return True
            
            # DOM이 완전히 로드될 때까지 대기 (동적 생성 요소 대응)
            logger.info("DOM 완전 로딩 대기 중... (3초)")
            await asyncio.sleep(3)
            
            # 네트워크 유휴 상태까지 추가 대기
            await page.wait_for_load_state('networkidle', timeout=10000)
            
            # 정확한 버튼 구조 기반 탐지 (사용자 제공 정보)
            logger.info("정확한 색인분류검색 버튼 구조로 탐지 시작...")
            
            # 1순위: 정확한 ID로 탐지
            exact_button_id = '#InfoBank_form_divMain_divWork1_btnIdxDiv'
            logger.info(f"[1단계] 정확한 ID로 탐지 시도: {exact_button_id}")
            
            btn_element = page.locator(exact_button_id)
            if await btn_element.count() > 0:
                logger.info("정확한 ID로 색인분류검색 버튼 발견!")
                if await btn_element.is_visible():
                    await btn_element.click()
                    logger.info("색인분류검색 버튼 클릭 성공 (ID 방식)")
                    await asyncio.sleep(3)
                    return await self.verify_modal_opened(page)
                else:
                    logger.warning("버튼이 존재하지만 비가시 상태입니다.")
            
            # 2순위: 텍스트 내용으로 정확히 탐지 (JavaScript evaluate 사용)
            logger.info("[2단계] 텍스트 내용 기반 정확 탐지 시도...")
            
            # JavaScript를 사용해 정확한 텍스트로 요소 찾기
            btn_by_text = await page.evaluate("""
                () => {
                    // 모든 div 요소를 순회하며 정확히 "색인분류검색" 텍스트를 포함한 요소 찾기
                    const allDivs = Array.from(document.querySelectorAll('div'));
                    for (let div of allDivs) {
                        const text = div.textContent?.trim();
                        if (text === '색인분류검색') {
                            return {
                                id: div.id,
                                className: div.className,
                                tagName: div.tagName,
                                text: text,
                                found: true
                            };
                        }
                    }
                    return { found: false };
                }
            """)
            
            if btn_by_text.get('found'):
                logger.info(f"텍스트 기반으로 버튼 발견: ID={btn_by_text.get('id')}, Class={btn_by_text.get('className')}")
                
                # 발견된 요소를 클릭
                text_selector = f"div:has-text('색인분류검색')"
                text_element = page.locator(text_selector).first
                
                if await text_element.count() > 0 and await text_element.is_visible():
                    await text_element.click()
                    logger.info("색인분류검색 버튼 클릭 성공 (텍스트 방식)")
                    await asyncio.sleep(3)
                    return await self.verify_modal_opened(page)
            
            # 3순위: 확장된 선택자로 재시도
            logger.info("[3단계] 확장 선택자로 재시도...")
            extended_selectors = [
                # ID 부분 매칭
                '[id*="InfoBank_form_divMain_divWork1_btnIdx"]',
                '[id*="btnIdxDiv"]',
                '[id*="divWork1_btn"]',
                
                # 정확한 텍스트 매칭
                'div >> text="색인분류검색"',
                '*:has-text("색인분류검색")',
                
                # 부모-자식 관계 활용
                '#InfoBank_form_divMain_divWork1 div:has-text("색인분류검색")',
                '[id*="divMain"] [id*="btnIdx"]',
                
                # Nexacro 패턴
                'div[id*="InfoBank_form"][id*="btn"]:has-text("색인분류")'
            ]
            
            for i, selector in enumerate(extended_selectors):
                try:
                    logger.info(f"[{i+1}/{len(extended_selectors)}] 확장 선택자 시도: {selector}")
                    
                    elements = page.locator(selector)
                    count = await elements.count()
                    
                    if count == 0:
                        logger.debug(f"선택자 '{selector}': 요소 없음")
                        continue
                    
                    # 여러 요소가 있다면 각각 시도
                    for j in range(min(count, 3)):  # 최대 3개까지만 시도
                        try:
                            btn = elements.nth(j)
                            
                            if not await btn.is_visible():
                                logger.debug(f"선택자 '{selector}' 요소 {j}: 비가시")
                                continue
                            
                            await btn.wait_for(state='enabled', timeout=3000)
                            await btn.click()
                            
                            logger.info(f"색인분류검색 버튼 클릭 성공: {selector}[{j}]")
                            await asyncio.sleep(3)  # 모달 로딩 대기
                            
                            # 모달이 열렸는지 확인
                            if await self.verify_modal_opened(page):
                                return True
                            
                        except Exception as e:
                            logger.debug(f"선택자 {selector}[{j}] 클릭 실패: {e}")
                            continue
                    
                except Exception as e:
                    logger.debug(f"선택자 {selector} 시도 실패: {e}")
                    continue
            
            # 최종 디버깅: 모든 시도가 실패한 경우 상세 정보 로깅
            logger.error("모든 방법으로 색인분류검색 버튼을 찾을 수 없습니다.")
            
            # 현재 페이지 상태 점검
            await page.evaluate("""
                () => {
                    console.log('=== 페이지 상태 점검 ===');
                    console.log('정확한 ID 요소:', document.querySelector('#InfoBank_form_divMain_divWork1_btnIdxDiv'));
                    console.log('색인분류검색 텍스트 요소:', Array.from(document.querySelectorAll('div')).find(el => el.textContent?.trim() === '색인분류검색'));
                    console.log('모든 버튼형 요소 수:', document.querySelectorAll('div[id*="btn"], button, input[type="button"]').length);
                }
            """)
            
            logger.error("상세 디버깅 정보가 브라우저 콘솔에 출력되었습니다.")
            return False
            
        except Exception as e:
            logger.error(f"색인분류검색 모달 열기 실패: {e}")
            return False
    
    async def extract_tree_items(self, page: Page, level_name: str) -> List[Dict]:
        """
        트리에서 특정 레벨의 항목들을 추출한다 (실제 HIRA 화면 구조 기반)
        
        Args:
            page: Playwright 페이지
            level_name: 레벨명 (대분류, 중분류, 소분류)
            
        Returns:
            추출된 항목 리스트 [{'text': '항목명', 'code': '코드', 'name': '명칭', 'element': Locator}]
        """
        try:
            logger.info(f"{level_name} 항목 추출 시작...")
            
            # 모달이 열린 상태에서 분류 그리드 요소들을 찾기
            tree_selectors = [
                # 1순위: 실제 modal_div.html 구조 기반 - 그리드 행
                '#InfoBank_RvStdInqIdxPL_form_grdIdxDiv1_body div[id*="gridrow"]:visible',
                'div[id*="RvStdInqIdxPL"] div[id*="gridrow"]:visible',
                'div[id*="grdIdxDiv1_body"] div[id*="gridrow"]:visible',
                
                # 2순위: 분류 항목 셀 구조
                'div[id*="grdIdxDiv1_body"] div[id*="cell"]:visible',
                'div[style*="cursor: pointer"][id*="cell"]:visible',
                
                # 3순위: 텍스트 컨테이너
                'div[id*="GridCellTextContainerElement"]:visible',
                'div[style*="table-cell"]:visible',
                
                # 4순위: 백업 선택자
                'div[tabindex]:visible',
                'div[style*="cursor: pointer"]:visible'
            ]
            
            items = []
            
            for selector in tree_selectors:
                try:
                    elements = page.locator(selector)
                    count = await elements.count()
                    
                    if count == 0:
                        continue
                        
                    logger.info(f"선택자 '{selector}'로 {count}개 요소 발견")
                    
                    # 각 요소에서 텍스트 추출 및 분류 (실제 화면 구조 분석)
                    for i in range(min(count, 30)):  # 더 많은 요소 확인
                        try:
                            element = elements.nth(i)
                            
                            if not await element.is_visible():
                                continue
                            
                            # 요소의 속성과 구조 분석
                            element_id = await element.get_attribute('id') or ''
                            element_class = await element.get_attribute('class') or ''
                            
                            text = await element.text_content()
                            if not text or not text.strip():
                                continue
                                
                            text = text.strip()
                            
                            # 그리드 셀 내부 구조 분석 시도
                            inner_elements = await element.locator('div, span').all()
                            if len(inner_elements) > 0:
                                # 셀 내부에 하위 요소가 있다면 각각 분석
                                for inner_elem in inner_elements:
                                    try:
                                        inner_text = await inner_elem.text_content()
                                        if inner_text and inner_text.strip() and inner_text.strip() != text:
                                            # 하위 요소의 텍스트가 더 구체적일 수 있음
                                            logger.debug(f"하위 요소 텍스트 발견: '{inner_text.strip()}'")
                                    except:
                                        continue
                            
                            # 모든 텍스트 요소 분석 (첫 15개만 로그 출력)
                            if i < 15:
                                logger.info(f"요소 분석 [{i}]: '{text}' (ID: {element_id[:50]}, Class: {element_class[:50]})")
                            
                            # 매우 관대한 필터링 - 거의 모든 텍스트 허용
                            skip_patterns = ['undefined', 'null']
                            
                            should_skip = False
                            for skip_pattern in skip_patterns:
                                if skip_pattern.lower() == text.lower():
                                    should_skip = True
                                    break
                            
                            if should_skip or len(text.strip()) < 1:
                                continue
                                
                            # HIRA 화면 구조에 맞는 코드와 명칭 분리
                            code = ""
                            name = text
                            
                            # 패턴 1: "A00000: 산정방법 및 일반원칙" 형태
                            if ':' in text:
                                parts = text.split(':', 1)
                                if len(parts) == 2:
                                    potential_code = parts[0].strip()
                                    potential_name = parts[1].strip()
                                    # 코드가 영문+숫자 패턴인지 확인
                                    if re.match(r'^[A-Z][0-9]*$', potential_code):
                                        code = potential_code
                                        name = potential_name
                            
                            # 패턴 2: "요양급여비용산정기준(행위)(A)" 형태
                            elif '(' in text and ')' in text:
                                # 마지막 괄호에서 코드 추출
                                last_paren_match = re.search(r'\(([A-Z][0-9]*)\)$', text)
                                if last_paren_match:
                                    code = last_paren_match.group(1)
                                    name = text[:last_paren_match.start()].strip()
                                else:
                                    # 괄호 안의 내용도 명칭에 포함
                                    name = text
                                    # 단순 영문 코드 찾기
                                    simple_code_match = re.search(r'[A-Z](?![가-힣])', text)
                                    if simple_code_match:
                                        code = simple_code_match.group(0)
                            
                            # 패턴 3: 단순 텍스트에서 코드 찾기
                            else:
                                # 영문+숫자 조합 찾기 (A, A01, A00000 등)
                                code_match = re.search(r'\b([A-Z][0-9]*)\b', text)
                                if code_match:
                                    code = code_match.group(1)
                                    # 코드를 제외한 나머지를 명칭으로
                                    name = re.sub(r'\b[A-Z][0-9]*\b', '', text).strip()
                                    if not name:
                                        name = text
                            
                            items.append({
                                'text': text,
                                'code': code,
                                'name': name,
                                'element': element,
                                'selector_used': selector,
                                'index': i
                            })
                            
                            logger.debug(f"유효한 항목 추가: '{text}' (코드: {code}, 명칭: {name})")
                            
                            # 첫 번째 항목에 대해서는 더 상세한 디버깅 정보 출력
                            if len(items) == 0:
                                logger.info(f"첫 번째 {level_name} 항목 상세 분석:")
                                logger.info(f"  - 전체 텍스트: '{text}'")
                                logger.info(f"  - 추출된 코드: '{code}'")
                                logger.info(f"  - 추출된 명칭: '{name}'")
                                logger.info(f"  - 요소 ID: {element_id}")
                                logger.info(f"  - 요소 Class: {element_class}")
                            
                        except Exception as e:
                            logger.debug(f"요소 {i} 처리 실패: {e}")
                            continue
                    
                    if items:
                        logger.info(f"{level_name}에서 {len(items)}개 항목 추출 완료 (선택자: {selector})")
                        break
                        
                except Exception as e:
                    logger.debug(f"선택자 '{selector}' 처리 실패: {e}")
                    continue
            
            # 중복 제거 (텍스트 기준)
            unique_items = []
            seen_texts = set()
            
            for item in items:
                if item['text'] not in seen_texts:
                    seen_texts.add(item['text'])
                    unique_items.append(item)
            
            logger.info(f"{level_name} 최종 {len(unique_items)}개 고유 항목 추출")
            return unique_items
            
        except Exception as e:
            logger.error(f"{level_name} 항목 추출 실패: {e}")
            return []
    
    async def get_input_field_value(self, page: Page) -> str:
        """검색 입력 필드에서 자동 입력된 값을 가져온다"""
        try:
            search_input = page.locator(self.selectors['search_input'])
            if await search_input.is_visible():
                value = await search_input.input_value()
                return value.strip() if value else ""
        except Exception as e:
            logger.debug(f"입력 필드 값 가져오기 실패: {e}")
        return ""
    
    async def traverse_classification_tree(self, context: BrowserContext, page: Page):
        """색인분류 트리를 완전히 순회하며 모든 계층 구조를 추출한다"""
        try:
            logger.info("색인분류 트리 순회 시작...")
            
            # 1단계: 대분류 목록 추출
            major_items = await self.extract_tree_items(page, "대분류")
            
            if not major_items:
                logger.error("대분류 항목을 찾을 수 없습니다.")
                return
                
            logger.info(f"총 {len(major_items)}개 대분류 발견")
            
            # 각 대분류별로 순회
            for major_idx, major_item in enumerate(major_items):
                try:
                    major_code = major_item['code']
                    major_name = major_item['name']
                    
                    logger.info(f"[{major_idx+1}/{len(major_items)}] 대분류 처리: {major_item['text']}")
                    
                    # 팝업 페이지 상태 확인
                    page = await self.ensure_popup_page(context, page)
                    
                    # 대분류 클릭 (가려진 요소 문제 해결)
                    try:
                        # 1순위: 일반 클릭
                        await major_item['element'].click()
                    except Exception as e:
                        logger.warning(f"일반 클릭 실패, 강제 클릭 시도: {e}")
                        try:
                            # 2순위: 강제 클릭 (intercepted 요소 무시)
                            await major_item['element'].click(force=True)
                        except Exception as e2:
                            logger.warning(f"강제 클릭도 실패, JavaScript 클릭 시도: {e2}")
                            # 3순위: JavaScript로 직접 클릭
                            await major_item['element'].evaluate('element => element.click()')
                    
                    await asyncio.sleep(2)  # 중분류 로딩 대기
                    
                    # 2단계: 중분류 목록 추출
                    middle_items = await self.extract_tree_items(page, "중분류")
                    
                    if not middle_items:
                        logger.warning(f"대분류 '{major_item['text']}'에 중분류가 없습니다.")
                        continue
                    
                    logger.info(f"  └ {len(middle_items)}개 중분류 발견")
                    
                    # 각 중분류별로 순회
                    for middle_idx, middle_item in enumerate(middle_items):
                        try:
                            middle_code = middle_item['code']
                            middle_name = middle_item['name']
                            
                            logger.info(f"    [{middle_idx+1}/{len(middle_items)}] 중분류 처리: {middle_item['text']}")
                            
                            # 팝업 페이지 상태 확인
                            page = await self.ensure_popup_page(context, page)
                            
                            # 중분류 클릭 (가려진 요소 문제 해결)
                            try:
                                await middle_item['element'].click()
                            except Exception as e:
                                logger.warning(f"중분류 일반 클릭 실패, 강제 클릭 시도: {e}")
                                try:
                                    await middle_item['element'].click(force=True)
                                except Exception as e2:
                                    logger.warning(f"중분류 강제 클릭도 실패, JavaScript 클릭 시도: {e2}")
                                    await middle_item['element'].evaluate('element => element.click()')
                            
                            await asyncio.sleep(2)  # 소분류 로딩 대기
                            
                            # 3단계: 소분류 목록 추출
                            minor_items = await self.extract_tree_items(page, "소분류")
                            
                            if not minor_items:
                                logger.warning(f"중분류 '{middle_item['text']}'에 소분류가 없습니다.")
                                continue
                                
                            logger.info(f"      └ {len(minor_items)}개 소분류 발견")
                            
                            # 각 소분류별로 순회
                            for minor_idx, minor_item in enumerate(minor_items):
                                try:
                                    minor_code = minor_item['code']
                                    minor_name = minor_item['name']
                                    
                                    logger.info(f"        [{minor_idx+1}/{len(minor_items)}] 소분류 처리: {minor_item['text']}")
                                    
                                    # 팝업 페이지 상태 확인
                                    page = await self.ensure_popup_page(context, page)
                                    
                                    # 소분류 클릭 (가려진 요소 문제 해결)
                                    try:
                                        await minor_item['element'].click()
                                    except Exception as e:
                                        logger.warning(f"소분류 일반 클릭 실패, 강제 클릭 시도: {e}")
                                        try:
                                            await minor_item['element'].click(force=True)
                                        except Exception as e2:
                                            logger.warning(f"소분류 강제 클릭도 실패, JavaScript 클릭 시도: {e2}")
                                            await minor_item['element'].evaluate('element => element.click()')
                                    
                                    await asyncio.sleep(1)
                                    
                                    # 입력 필드에서 자동 입력된 코드 확인
                                    auto_input_code = await self.get_input_field_value(page)
                                    
                                    # 데이터 저장
                                    classification_data = {
                                        '대분류코드': major_code,
                                        '대분류명': major_name,
                                        '중분류코드': middle_code,
                                        '중분류명': middle_name,
                                        '소분류코드': minor_code or auto_input_code,
                                        '소분류명': minor_name,
                                        '자동입력코드': auto_input_code
                                    }
                                    
                                    self.classification_data.append(classification_data)
                                    
                                    logger.info(f"          └ 저장: {classification_data['소분류코드']} - {classification_data['소분류명']}")
                                    
                                except Exception as e:
                                    logger.error(f"소분류 '{minor_item['text']}' 처리 실패: {e}")
                                    continue
                                    
                        except Exception as e:
                            logger.error(f"중분류 '{middle_item['text']}' 처리 실패: {e}")
                            continue
                            
                except Exception as e:
                    logger.error(f"대분류 '{major_item['text']}' 처리 실패: {e}")
                    continue
                    
            logger.info(f"트리 순회 완료. 총 {len(self.classification_data)}개 항목 수집")
            
        except Exception as e:
            logger.error(f"트리 순회 중 오류 발생: {e}")
    
    async def close_modal(self, page: Page):
        """모달을 닫는다"""
        try:
            close_selectors = [
                'button:has-text("닫기")',
                'button:has-text("확인")',
                'button:has-text("취소")',
                '[title="닫기"]',
                '.close-btn',
                '[class*="close"]'
            ]
            
            for selector in close_selectors:
                try:
                    close_btn = page.locator(selector).first
                    if await close_btn.is_visible():
                        await close_btn.click()
                        logger.info("모달을 닫았습니다.")
                        await asyncio.sleep(2)
                        return
                except:
                    continue
                    
            logger.warning("모달 닫기 버튼을 찾을 수 없습니다.")
            
        except Exception as e:
            logger.error(f"모달 닫기 실패: {e}")
            
    def save_to_csv(self):
        """수집된 데이터를 CSV 파일로 저장한다"""
        try:
            if not self.classification_data:
                logger.warning("저장할 데이터가 없습니다.")
                return
                
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            csv_filename = self.output_dir / f"hira_classification_map_{timestamp}.csv"
            
            # CSV 파일 작성
            with open(csv_filename, 'w', newline='', encoding='utf-8-sig') as csvfile:
                fieldnames = ['대분류코드', '대분류명', '중분류코드', '중분류명', '소분류코드', '소분류명', '자동입력코드']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                
                writer.writeheader()
                for data in self.classification_data:
                    writer.writerow(data)
            
            logger.info(f"CSV 파일 저장 완료: {csv_filename}")
            logger.info(f"총 {len(self.classification_data)}개 항목 저장")
            
            # 요약 통계
            major_count = len(set(item['대분류코드'] for item in self.classification_data))
            middle_count = len(set(f"{item['대분류코드']}-{item['중분류코드']}" for item in self.classification_data))
            minor_count = len(self.classification_data)
            
            logger.info(f"수집 통계: 대분류 {major_count}개, 중분류 {middle_count}개, 소분류 {minor_count}개")
            
        except Exception as e:
            logger.error(f"CSV 저장 실패: {e}")
    
    async def run(self):
        """크롤링 메인 실행 함수"""
        logger.info("HIRA 색인분류 계층 구조 추출 시작")
        
        try:
            # 브라우저 설정
            browser, context = await self.setup_browser()
            
            try:
                # 1. 메인 페이지 열고 Nexacro 세션 확보
                await self.open_main_page(context)
                
                # 2. 팝업 페이지 열기
                page = await self.open_popup_page(context)
                
                # 색인분류검색 모달 열기
                if not await self.open_classification_modal(page):
                    logger.error("색인분류검색 모달 열기 실패")
                    return
                
                # 분류 트리 순회 및 데이터 추출
                await self.traverse_classification_tree(context, page)
                
                # 모달 닫기
                await self.close_modal(page)
                
                # 결과를 CSV로 저장
                self.save_to_csv()
                
            finally:
                try:
                    await context.close()
                    await browser.close()
                    logger.info("브라우저 정리 완료")
                except Exception as e:
                    logger.warning(f"브라우저 정리 중 오류: {e}")
                    
        except Exception as e:
            logger.error(f"크롤링 실행 중 오류: {e}")
            raise

async def main():
    """메인 실행 함수"""
    output_directory = "./output"
    
    mapper = HIRAClassificationMapper(output_directory)
    await mapper.run()

if __name__ == "__main__":
    asyncio.run(main())