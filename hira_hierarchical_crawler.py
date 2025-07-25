"""
HIRA 요양기관 업무포털 3단계 계층구조 크롤러
대분류 → 중분류 → 소분류의 3단계 구조를 순회하여 모든 항목을 추출하고 JSON/CSV로 저장
"""

import asyncio
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
import pandas as pd
from playwright.async_api import async_playwright, Page, Browser, BrowserContext

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('hira_hierarchical_crawler.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class HIRAHierarchicalCrawler:
    def __init__(self, output_dir: str = "./output"):
        """
        HIRA 3단계 계층구조 크롤러 초기화
        
        Args:
            output_dir: 결과 파일 저장 디렉토리
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        
        # HIRA 웹사이트 URL
        self.main_url = "https://biz.hira.or.kr/index.do"
        self.popup_url = "https://biz.hira.or.kr/popup.ndo?formname=qya_bizcom%3A%3AInfoBank.xfdl&framename=InfoBank"
        
        # DOM 선택자 (사용자 제공)
        self.selectors = {
            # 대분류 선택자
            'major_container': '#InfoBank_RvStdInqIdxPL_form_grdIdxDiv1_bodyGridBandContainerElement_inner',
            'major_textbox': '#InfoBank_RvStdInqIdxPL_form_grdIdxDiv1_bodyTextBoxElement',
            'major_item_base': 'InfoBank_RvStdInqIdxPL_form_grdIdxDiv1_body_gridrow_',
            
            # 중분류 선택자
            'middle_container': '#InfoBank_RvStdInqIdxPL_form_grdIdxDiv2_bodyGridBandContainerElement_inner',
            'middle_textbox': '#InfoBank_RvStdInqIdxPL_form_grdIdxDiv2_bodyTextBoxElement',
            'middle_item_base': 'InfoBank_RvStdInqIdxPL_form_grdIdxDiv2_body_gridrow_',
            
            # 소분류 선택자
            'minor_container': '#InfoBank_RvStdInqIdxPL_form_grdIdxDiv3_bodyGridBandContainerElement_inner',
            'minor_textbox': '#InfoBank_RvStdInqIdxPL_form_grdIdxDiv3_bodyTextBoxElement',
            'minor_item_base': 'InfoBank_RvStdInqIdxPL_form_grdIdxDiv3_body_gridrow_',
            
            # 기타 (성공한 코드에서 가져온 선택자)
            'classification_search_btn': 'text=색인분류 검색',
            'modal_close_btn': 'text=닫기',
            'search_input': '#InfoBank_form_divMain_divWork1_edtSearchTxt_input',
            'search_button': '#InfoBank_form_divMain_divWork1_btnS0001',
            'excel_button': '#InfoBank_form_divMain_divWork1_btnE0001TextBoxElement'
        }
        
        # 수집된 데이터
        self.hierarchical_data: List[Dict] = []
        
    def parse_korean_text(self, text: str) -> Dict[str, str]:
        """
        한국어 텍스트에서 명칭과 코드를 분리
        
        지원 형식:
        1. "산정방법 및 일반원칙(A00000)" → name: "산정방법 및 일반원칙", code: "A00000"
        2. "00 일반원칙" → name: "일반원칙", code: "00"
        3. "일반원칙 (00)" → name: "일반원칙", code: "00"
        
        Args:
            text: 파싱할 텍스트
            
        Returns:
            {"name": "명칭", "code": "코드"}
        """
        try:
            text = text.strip()
            
            # 패턴 1: "명칭(코드)" 형식
            match1 = re.match(r'^(.+?)\s*\(([^)]+)\)\s*$', text)
            if match1:
                name = match1.group(1).strip()
                code = match1.group(2).strip()
                return {"name": name, "code": code}
            
            # 패턴 2: "코드 명칭" 형식 (숫자나 영문으로 시작하는 코드)
            match2 = re.match(r'^([A-Z0-9]+)\s+(.+)$', text)
            if match2:
                code = match2.group(1).strip()
                name = match2.group(2).strip()
                return {"name": name, "code": code}
            
            # 패턴 3: "숫자+문자" 로 시작하는 경우 (예: "000 산정방법")
            match3 = re.match(r'^(\d+[A-Z]*)\s+(.+)$', text)
            if match3:
                code = match3.group(1).strip()
                name = match3.group(2).strip()
                return {"name": name, "code": code}
            
            # 매칭되지 않는 경우 전체를 명칭으로 처리
            return {"name": text, "code": ""}
                
        except Exception as e:
            logger.warning(f"텍스트 파싱 실패 '{text}': {e}")
            return {"name": text, "code": ""}
    
    async def setup_browser(self) -> tuple[Browser, BrowserContext, Page, Page]:
        """브라우저 설정 및 메인/팝업 페이지 생성"""
        playwright = await async_playwright().start()
        
        browser = await playwright.chromium.launch(
            headless=False,
            slow_mo=1000,  # 동작 확인을 위해 1초 대기  
            args=['--disable-web-security', '--disable-features=VizDisplayCompositor']
        )
        
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080}
        )
        
        # 메인 페이지 생성 및 접속
        main_page = await context.new_page()
        logger.info(f"메인 페이지 접속: {self.main_url}")
        await main_page.goto(self.main_url, wait_until='networkidle', timeout=30000)
        
        # Nexacro 메인 애플리케이션 로딩 대기
        logger.info("Nexacro 메인 애플리케이션 로딩 대기...")
        await asyncio.sleep(10)
        
        # 심사기준 종합서비스 메뉴 찾기 및 클릭
        menu_link = main_page.locator('text=심사기준 종합서비스')
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
            
            return browser, context, main_page, popup_page
        else:
            logger.error("심사기준 종합서비스 메뉴를 찾을 수 없습니다.")
            raise Exception("메뉴 링크를 찾을 수 없습니다")
    
    async def open_classification_modal(self, page: Page) -> bool:
        """색인분류검색 모달을 연다 (성공한 방법 사용)"""
        try:
            logger.info("색인분류검색 모달 열기 시도...")
            
            # DOM 완전 로딩 대기
            await asyncio.sleep(3)
            await page.wait_for_load_state('networkidle', timeout=10000)
            
            # 정확한 버튼 ID로 클릭 (성공한 코드에서 가져옴)
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
    
    async def close_classification_modal(self, page: Page):
        """분류 모달 닫기"""
        try:
            close_selectors = [
                'text=닫기',
                'text=확인', 
                'button:has-text("닫기")',
                'button:has-text("확인")',
                '[title="닫기"]'
            ]
            
            for selector in close_selectors:
                try:
                    close_btn = page.locator(selector).first
                    if await close_btn.is_visible():
                        await close_btn.click()
                        logger.info("분류 모달을 닫았습니다.")
                        await asyncio.sleep(2)
                        return
                except:
                    continue
                    
            logger.warning("모달 닫기 버튼을 찾을 수 없습니다.")
            
        except Exception as e:
            logger.error(f"모달 닫기 실패: {e}")
    
    async def get_level_items(self, page: Page, level: str) -> List[Dict[str, str]]:
        """
        특정 레벨의 모든 항목을 가져온다 (성공 검증된 방식)
        
        Args:
            page: Playwright 페이지
            level: 'major', 'middle', 'minor' 중 하나
            
        Returns:
            항목 리스트 [{"name": "명칭", "code": "코드", "index": 0}, ...]
        """
        items = []
        item_base = self.selectors[f'{level}_item_base']
        
        try:
            # 컨테이너가 로딩될 때까지 대기
            container_selector = self.selectors[f'{level}_container']
            container = None
            try:
                container = page.locator(container_selector)
                await container.wait_for(state='visible', timeout=10000)
                await asyncio.sleep(2)  # Nexacro 렌더링 추가 대기
            except:
                logger.warning(f"{level} 레벨 컨테이너 로딩 대기 실패")
            
            # 간단하고 확실한 스크롤로 모든 요소 로딩
            if container:
                try:
                    # 끝까지 여러 번 스크롤하여 모든 요소 로딩 확보
                    for _ in range(50):  # 50회 스크롤
                        await container.evaluate('el => el.scrollTop += 100')
                        await asyncio.sleep(0.2)
                    
                    # 맨 아래까지 스크롤
                    await container.evaluate('el => el.scrollTop = el.scrollHeight')
                    await asyncio.sleep(1)
                    
                    # 맨 위로 복귀
                    await container.evaluate('el => el.scrollTop = 0')
                    await asyncio.sleep(1)
                    
                except Exception as e:
                    logger.warning(f"스크롤 실패: {e}")
            
            # 성공 검증된 방식: ID 기반 순차 접근
            index = 0
            consecutive_failures = 0
            
            while consecutive_failures < 10:  # 연속 실패 10회까지 허용
                # ID 기반으로 각 항목 찾기
                item_id = f"{item_base}{index}"
                item_element = page.locator(f"#{item_id}")
                
                # 요소 존재 확인
                if await item_element.count() == 0:
                    consecutive_failures += 1
                    index += 1
                    continue
                
                # 요소 가시성 확인 및 스크롤
                if not await item_element.is_visible():
                    try:
                        await item_element.scroll_into_view_if_needed()
                        await asyncio.sleep(0.1)
                    except:
                        pass
                    
                    if not await item_element.is_visible():
                        consecutive_failures += 1
                        index += 1
                        continue
                
                # 텍스트 추출
                try:
                    inner_text = await item_element.evaluate('el => el.innerText')
                    if not inner_text:
                        inner_text = await item_element.text_content()
                    
                    if inner_text and inner_text.strip():
                        parsed = self.parse_korean_text(inner_text.strip())
                        item_data = {
                            "name": parsed["name"],
                            "code": parsed["code"],
                            "index": index,
                            "element_id": item_id,
                            "raw_text": inner_text.strip()
                        }
                        items.append(item_data)
                        logger.debug(f"{level} 레벨 항목 발견: {item_data}")
                        consecutive_failures = 0  # 성공시 카운터 리셋
                        
                except Exception as e:
                    logger.warning(f"{level} 레벨 {item_id} 텍스트 추출 실패: {e}")
                    consecutive_failures += 1
                
                index += 1
                
                # 무한 루프 방지 (최대 1000개)
                if index > 1000:
                    logger.warning(f"{level} 레벨: 최대 항목 수 초과. 탐색 중단")
                    break
            
            logger.info(f"{level} 레벨에서 {len(items)}개 항목 발견")
            return items
            
        except Exception as e:
            logger.error(f"{level} 레벨 항목 가져오기 실패: {e}")
            return []
    
    async def click_item(self, page: Page, item: Dict[str, str]) -> bool:
        """
        특정 항목 클릭
        
        Args:
            page: Playwright 페이지
            item: 클릭할 항목 정보
            
        Returns:
            클릭 성공 여부
        """
        try:
            element_id = item["element_id"]
            item_element = page.locator(f"#{element_id}")
            
            # 요소 존재 및 가시성 확인
            if await item_element.count() == 0:
                logger.warning(f"항목 {element_id} 요소가 존재하지 않음")
                return False
                
            if not await item_element.is_visible():
                logger.warning(f"항목 {element_id} 요소가 보이지 않음")
                return False
            
            # 클릭
            await item_element.click()
            logger.info(f"항목 클릭 성공: {item['name']} ({item['code']})")
            
            # 하위 항목 로딩 대기
            await asyncio.sleep(2)
            return True
            
        except Exception as e:
            logger.error(f"항목 클릭 실패 {item['name']}: {e}")
            return False
    
    async def crawl_hierarchy(self, page: Page) -> None:
        """3단계 계층구조 크롤링 메인 로직"""
        try:
            logger.info("=== 3단계 계층구조 크롤링 시작 ===")
            
            # 1단계: 대분류 항목들 가져오기
            major_items = await self.get_level_items(page, 'major')
            if not major_items:
                logger.error("대분류 항목을 찾을 수 없습니다.")
                return
            
            logger.info(f"대분류 {len(major_items)}개 발견")
            
            # 각 대분류 순회
            for major_idx, major_item in enumerate(major_items):
                logger.info(f"\n[대분류 {major_idx + 1}/{len(major_items)}] {major_item['name']} ({major_item['code']})")
                
                # 대분류 클릭
                if not await self.click_item(page, major_item):
                    logger.error(f"대분류 {major_item['name']} 클릭 실패")
                    continue
                
                # 2단계: 중분류 항목들 가져오기
                middle_items = await self.get_level_items(page, 'middle')
                if not middle_items:
                    logger.warning(f"대분류 {major_item['name']}에 중분류 항목이 없습니다.")
                    continue
                
                logger.info(f"  중분류 {len(middle_items)}개 발견")
                
                # 각 중분류 순회
                for middle_idx, middle_item in enumerate(middle_items):
                    logger.info(f"  [중분류 {middle_idx + 1}/{len(middle_items)}] {middle_item['name']} ({middle_item['code']})")
                    
                    # 중분류 클릭
                    if not await self.click_item(page, middle_item):
                        logger.error(f"중분류 {middle_item['name']} 클릭 실패")
                        continue
                    
                    # 3단계: 소분류 항목들 가져오기
                    minor_items = await self.get_level_items(page, 'minor')
                    if not minor_items:
                        logger.warning(f"중분류 {middle_item['name']}에 소분류 항목이 없습니다.")
                        continue
                    
                    logger.info(f"    소분류 {len(minor_items)}개 발견")
                    
                    # 각 소분류 순회
                    for minor_idx, minor_item in enumerate(minor_items):
                        logger.info(f"    [소분류 {minor_idx + 1}/{len(minor_items)}] {minor_item['name']} ({minor_item['code']})")
                        
                        # 계층구조 데이터 저장
                        hierarchy_record = {
                            "대분류코드": major_item["code"],
                            "대분류명": major_item["name"],
                            "중분류코드": middle_item["code"],
                            "중분류명": middle_item["name"],
                            "소분류코드": minor_item["code"],
                            "소분류명": minor_item["name"],
                            "수집시간": datetime.now().isoformat()
                        }
                        
                        self.hierarchical_data.append(hierarchy_record)
                        logger.debug(f"계층구조 데이터 저장: {hierarchy_record}")
                    
                    # 다음 중분류로 이동하기 전 잠시 대기
                    await asyncio.sleep(1)
                
                # 다음 대분류로 이동하기 전 잠시 대기
                await asyncio.sleep(1)
            
            logger.info(f"\n=== 계층구조 크롤링 완료 ===")
            logger.info(f"총 {len(self.hierarchical_data)}개의 소분류 수집")
            
        except Exception as e:
            logger.error(f"계층구조 크롤링 중 오류: {e}")
    
    def save_results(self) -> None:
        """수집된 데이터를 JSON과 CSV로 저장"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            if not self.hierarchical_data:
                logger.warning("저장할 데이터가 없습니다.")
                return
            
            # JSON 저장
            json_file = self.output_dir / f"hira_hierarchy_{timestamp}.json"
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(self.hierarchical_data, f, ensure_ascii=False, indent=2)
            logger.info(f"JSON 파일 저장: {json_file}")
            
            # CSV 저장
            csv_file = self.output_dir / f"hira_hierarchy_{timestamp}.csv"
            df = pd.DataFrame(self.hierarchical_data)
            df.to_csv(csv_file, index=False, encoding='utf-8-sig')
            logger.info(f"CSV 파일 저장: {csv_file}")
            
            # 통계 정보 저장
            stats = {
                "총_소분류_수": len(self.hierarchical_data),
                "대분류_수": len(df['대분류코드'].unique()),
                "중분류_수": len(df[['대분류코드', '중분류코드']].drop_duplicates()),
                "수집_완료_시간": datetime.now().isoformat()
            }
            
            stats_file = self.output_dir / f"hira_hierarchy_stats_{timestamp}.json"
            with open(stats_file, 'w', encoding='utf-8') as f:
                json.dump(stats, f, ensure_ascii=False, indent=2)
            logger.info(f"통계 파일 저장: {stats_file}")
            
            logger.info(f"결과 저장 완료: {len(self.hierarchical_data)}개 항목")
            
        except Exception as e:
            logger.error(f"결과 저장 실패: {e}")
    
    async def run(self):
        """크롤링 메인 실행 함수"""
        logger.info("HIRA 3단계 계층구조 크롤링 시작")
        
        try:
            # 브라우저 설정 (메인 페이지 + 팝업 페이지)
            browser, context, main_page, popup_page = await self.setup_browser()
            
            try:
                # 성공한 방법: 메인에서 팝업을 이미 열었으므로 별도 goto 불필요
                
                # 색인분류 모달 열기
                if not await self.open_classification_modal(popup_page):
                    logger.error("색인분류 모달 열기 실패")
                    return
                
                # 계층구조 크롤링 실행
                await self.crawl_hierarchy(popup_page)
                
                # 모달 닫기
                await self.close_classification_modal(popup_page)
                
                # 결과 저장
                self.save_results()
                
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
    
    crawler = HIRAHierarchicalCrawler(output_directory)
    await crawler.run()

if __name__ == "__main__":
    asyncio.run(main())