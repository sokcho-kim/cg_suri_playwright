"""
HIRA 요양기관 업무포털 색인분류 검색 기반 자동화 크롤러
대분류 → 중분류 → 소분류 클릭으로 수가코드를 입력하여 엑셀 다운로드
"""

import asyncio
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import pandas as pd
from playwright.async_api import async_playwright, Page, Browser, BrowserContext

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('hira_classification_crawler.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class HIRAClassificationCrawler:
    def __init__(self, excel_file_path: str, classification_mapping_file: str, download_dir: str = "./downloads"):
        """
        HIRA 색인분류 검색 크롤러 초기화
        
        Args:
            excel_file_path: 수가코드가 포함된 엑셀 파일 경로
            classification_mapping_file: 수가코드-분류경로 매핑 엑셀 파일 경로
            download_dir: 다운로드 디렉토리 경로
        """
        self.excel_file_path = excel_file_path
        self.classification_mapping_file = classification_mapping_file
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(exist_ok=True)
        
        # HIRA 웹사이트 URL 및 CSS 선택자
        self.popup_url = "https://biz.hira.or.kr/popup.ndo?formname=qya_bizcom%3A%3AInfoBank.xfdl&framename=InfoBank"
        self.selectors = {
            'classification_search_btn': 'text=색인분류 검색',  # 색인분류 검색 버튼
            'search_button': '#InfoBank_form_divMain_divWork1_btnS0001',  # 조회 버튼
            'excel_button': '#InfoBank_form_divMain_divWork1_btnE0001TextBoxElement',  # 엑셀 다운로드 버튼
            'search_input': '#InfoBank_form_divMain_divWork1_edtSearchTxt_input',  # 검색 입력창 (확인용)
            'modal_close_btn': 'text=닫기'  # 모달 닫기 버튼
        }
        
        # 분류 경로 매핑 데이터
        self.code_classification_map: Dict[str, Dict] = {}
        
        # 다운로드 결과 추적
        self.results: List[Dict] = []
        
    def read_excel_codes(self) -> List[str]:
        """
        엑셀 파일에서 수가코드 목록을 읽어온다.
        
        Returns:
            수가코드 리스트
        """
        try:
            df = pd.read_excel(self.excel_file_path)
            codes = df.iloc[:, 0].astype(str).tolist()
            codes = [code.strip() for code in codes if pd.notna(code) and str(code).strip()]
            
            logger.info(f"엑셀 파일에서 {len(codes)}개의 수가코드를 읽었습니다.")
            return codes
            
        except Exception as e:
            logger.error(f"엑셀 파일 읽기 실패: {e}")
            raise
    
    def read_classification_mapping(self) -> Dict[str, Dict]:
        """
        수가코드-분류경로 매핑 파일을 읽어온다.
        
        예상 파일 형식:
        코드 | 대분류 | 중분류 | 소분류
        A001 | 진료비 | 기본진료료 | 외래진료료
        
        Returns:
            매핑 딕셔너리
        """
        try:
            df = pd.read_excel(self.classification_mapping_file)
            mapping = {}
            
            for _, row in df.iterrows():
                code = str(row.iloc[0]).strip()  # 첫 번째 컬럼: 코드
                if pd.notna(code) and code:
                    mapping[code] = {
                        'major': str(row.iloc[1]).strip() if pd.notna(row.iloc[1]) else '',  # 대분류
                        'middle': str(row.iloc[2]).strip() if pd.notna(row.iloc[2]) else '',  # 중분류
                        'minor': str(row.iloc[3]).strip() if pd.notna(row.iloc[3]) else ''   # 소분류
                    }
            
            logger.info(f"분류 매핑 파일에서 {len(mapping)}개의 매핑을 읽었습니다.")
            return mapping
            
        except Exception as e:
            logger.error(f"분류 매핑 파일 읽기 실패: {e}")
            raise
    
    async def setup_browser(self) -> tuple[Browser, BrowserContext, Page]:
        """
        브라우저 설정 및 페이지 생성
        
        Returns:
            browser, context, page 튜플
        """
        playwright = await async_playwright().start()
        
        browser = await playwright.chromium.launch(
            headless=False,  # GUI 모드로 실행하여 클릭 동작 확인 가능
            slow_mo=1500     # 동작 간 1.5초 대기 (클릭 동작을 명확히 확인)
        )
        
        context = await browser.new_context(
            accept_downloads=True,
            viewport={'width': 1920, 'height': 1080}
        )
        
        page = await context.new_page()
        
        # 다운로드 이벤트 리스너 추가
        page.on('download', self._handle_download)
        
        return browser, context, page
    
    async def _handle_download(self, download):
        """다운로드 이벤트 핸들러"""
        try:
            filename = f"temp_{int(time.time())}_{download.suggested_filename}"
            await download.save_as(self.download_dir / filename)
            logger.info(f"파일 다운로드 완료: {filename}")
        except Exception as e:
            logger.error(f"다운로드 처리 실패: {e}")
    
    async def open_classification_modal(self, page: Page) -> bool:
        """
        색인분류 검색 모달을 연다.
        
        Args:
            page: Playwright 페이지 객체
            
        Returns:
            모달 열기 성공 여부
        """
        try:
            logger.info("색인분류 검색 버튼을 찾고 있습니다...")
            
            # 색인분류 검색 버튼 찾기 (여러 가능한 선택자 시도)
            classification_selectors = [
                'text=색인분류 검색',
                'button:has-text("색인분류")',
                '[title*="색인분류"]',
                '[onclick*="classification"]',
                'input[value*="색인분류"]'
            ]
            
            classification_btn = None
            for selector in classification_selectors:
                try:
                    btn = page.locator(selector)
                    if await btn.is_visible():
                        classification_btn = btn
                        logger.info(f"색인분류 검색 버튼 발견: {selector}")
                        break
                except:
                    continue
            
            if classification_btn is None:
                logger.error("색인분류 검색 버튼을 찾을 수 없습니다.")
                return False
            
            # 버튼이 활성화될 때까지 대기
            await classification_btn.wait_for(state='enabled', timeout=10000)
            
            # 클릭 전 페이지 상태 확인
            await asyncio.sleep(2)
            
            # 색인분류 검색 버튼 클릭
            logger.info("색인분류 검색 버튼을 클릭합니다...")
            await classification_btn.click()
            
            # 모달이 나타날 때까지 대기
            await asyncio.sleep(3)
            
            logger.info("색인분류 검색 모달이 열렸습니다.")
            return True
            
        except Exception as e:
            logger.error(f"색인분류 모달 열기 실패: {e}")
            return False
    
    async def navigate_classification_tree(self, page: Page, major: str, middle: str, minor: str) -> bool:
        """
        분류 트리를 탐색하여 대분류 → 중분류 → 소분류 순으로 클릭한다.
        
        Args:
            page: Playwright 페이지 객체
            major: 대분류명
            middle: 중분류명  
            minor: 소분류명
            
        Returns:
            분류 선택 성공 여부
        """
        try:
            logger.info(f"분류 경로 탐색 시작: {major} → {middle} → {minor}")
            
            # 1단계: 대분류 클릭
            logger.info(f"대분류 '{major}' 클릭 시도...")
            major_selectors = [
                f'text={major}',
                f'[title="{major}"]',
                f'span:has-text("{major}")',
                f'div:has-text("{major}")',
                f'td:has-text("{major}")'
            ]
            
            major_clicked = False
            for selector in major_selectors:
                try:
                    major_element = page.locator(selector).first
                    if await major_element.is_visible():
                        await major_element.click()
                        logger.info(f"대분류 '{major}' 클릭 성공")
                        major_clicked = True
                        break
                except:
                    continue
            
            if not major_clicked:
                logger.error(f"대분류 '{major}'를 찾을 수 없습니다.")
                return False
            
            # 중분류가 로드될 때까지 대기
            await asyncio.sleep(2)
            
            # 2단계: 중분류 클릭
            logger.info(f"중분류 '{middle}' 클릭 시도...")
            middle_selectors = [
                f'text={middle}',
                f'[title="{middle}"]',
                f'span:has-text("{middle}")',
                f'div:has-text("{middle}")',
                f'td:has-text("{middle}")'
            ]
            
            middle_clicked = False
            for selector in middle_selectors:
                try:
                    middle_element = page.locator(selector).first
                    if await middle_element.is_visible():
                        await middle_element.click()
                        logger.info(f"중분류 '{middle}' 클릭 성공")
                        middle_clicked = True
                        break
                except:
                    continue
            
            if not middle_clicked:
                logger.error(f"중분류 '{middle}'를 찾을 수 없습니다.")
                return False
            
            # 소분류가 로드될 때까지 대기
            await asyncio.sleep(2)
            
            # 3단계: 소분류 클릭
            logger.info(f"소분류 '{minor}' 클릭 시도...")
            minor_selectors = [
                f'text={minor}',
                f'[title="{minor}"]',
                f'span:has-text("{minor}")',
                f'div:has-text("{minor}")',
                f'td:has-text("{minor}")'
            ]
            
            minor_clicked = False
            for selector in minor_selectors:
                try:
                    minor_element = page.locator(selector).first
                    if await minor_element.is_visible():
                        await minor_element.click()
                        logger.info(f"소분류 '{minor}' 클릭 성공")
                        minor_clicked = True
                        break
                except:
                    continue
            
            if not minor_clicked:
                logger.error(f"소분류 '{minor}'를 찾을 수 없습니다.")
                return False
            
            # 소분류 클릭 후 검색창에 코드가 입력될 때까지 대기
            await asyncio.sleep(3)
            
            logger.info(f"분류 경로 탐색 완료: {major} → {middle} → {minor}")
            return True
            
        except Exception as e:
            logger.error(f"분류 트리 탐색 실패: {e}")
            return False
    
    async def close_classification_modal(self, page: Page):
        """분류 모달을 닫는다."""
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
                    close_btn = page.locator(selector)
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
    
    async def search_and_download_by_classification(self, page: Page, code: str) -> Dict:
        """
        색인분류를 통해 수가코드를 검색하고 엑셀 파일을 다운로드한다.
        
        Args:
            page: Playwright 페이지 객체
            code: 수가코드
            
        Returns:
            처리 결과 딕셔너리
        """
        result = {
            'code': code,
            'success': False,
            'error': None,
            'filename': None,
            'timestamp': datetime.now().isoformat()
        }
        
        try:
            logger.info(f"수가코드 '{code}' 색인분류 검색 시작")
            
            # 1. 분류 매핑 확인
            if code not in self.code_classification_map:
                result['error'] = "분류 매핑 정보 없음"
                logger.warning(f"수가코드 '{code}': 분류 매핑 정보가 없습니다.")
                return result
            
            classification = self.code_classification_map[code]
            major = classification['major']
            middle = classification['middle']
            minor = classification['minor']
            
            if not all([major, middle, minor]):
                result['error'] = "분류 정보 불완전"
                logger.warning(f"수가코드 '{code}': 분류 정보가 불완전합니다. ({major}, {middle}, {minor})")
                return result
            
            # 2. 색인분류 검색 모달 열기
            if not await self.open_classification_modal(page):
                result['error'] = "색인분류 모달 열기 실패"
                return result
            
            # 3. 분류 트리 탐색
            if not await self.navigate_classification_tree(page, major, middle, minor):
                result['error'] = "분류 트리 탐색 실패"
                await self.close_classification_modal(page)
                return result
            
            # 4. 모달 닫기
            await self.close_classification_modal(page)
            
            # 5. 검색창에 코드가 입력되었는지 확인
            search_input = page.locator(self.selectors['search_input'])
            input_value = await search_input.input_value()
            logger.info(f"검색창 입력값 확인: '{input_value}'")
            
            # 6. 조회 버튼 클릭
            search_button = page.locator(self.selectors['search_button'])
            await search_button.wait_for(state='visible', timeout=10000)
            await search_button.wait_for(state='enabled', timeout=5000)
            await search_button.click()
            
            logger.info("조회 버튼 클릭 완료")
            
            # 7. 조회 결과 로딩 대기
            await asyncio.sleep(5)
            
            # 8. 엑셀 다운로드 버튼 클릭
            excel_button = page.locator(self.selectors['excel_button'])
            
            try:
                await excel_button.wait_for(state='visible', timeout=10000)
                await excel_button.wait_for(state='enabled', timeout=5000)
                
                # 다운로드 시작
                async with page.expect_download(timeout=30000) as download_info:
                    await excel_button.click()
                    
                download = await download_info.value
                
                # 파일명 생성 (수가코드 포함)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{code}_{timestamp}_{download.suggested_filename}"
                filepath = self.download_dir / filename
                
                # 파일 저장
                await download.save_as(filepath)
                
                result['success'] = True
                result['filename'] = filename
                logger.info(f"다운로드 성공: {filename}")
                
            except Exception as e:
                logger.warning(f"수가코드 '{code}': 다운로드 불가 - {str(e)}")
                result['error'] = f"다운로드 불가: {str(e)}"
                
                # 조회 결과가 없는지 확인
                try:
                    no_data_msg = page.locator("text=조회된 데이터가 없습니다")
                    if await no_data_msg.is_visible():
                        result['error'] = "조회 결과 없음"
                        logger.info(f"수가코드 '{code}': 조회 결과 없음")
                except:
                    pass
            
        except Exception as e:
            logger.error(f"수가코드 '{code}' 처리 중 오류 발생: {e}")
            result['error'] = str(e)
        
        return result
    
    async def run(self):
        """크롤링 메인 실행 함수"""
        logger.info("HIRA 색인분류 검색 크롤링 시작")
        
        try:
            # 1. 데이터 파일 읽기
            codes = self.read_excel_codes()
            self.code_classification_map = self.read_classification_mapping()
            
            if not codes:
                logger.error("수가코드가 없습니다.")
                return
                
            if not self.code_classification_map:
                logger.error("분류 매핑 데이터가 없습니다.")
                return
            
            # 2. 브라우저 설정
            browser, context, page = await self.setup_browser()
            
            try:
                # 3. HIRA 팝업 페이지 접속
                logger.info(f"웹사이트 접속: {self.popup_url}")
                await page.goto(self.popup_url, wait_until='networkidle', timeout=30000)
                
                # 페이지 로딩 완료 대기
                await asyncio.sleep(5)
                
                # 4. 각 수가코드별 처리
                total_codes = len(codes)
                success_count = 0
                
                for idx, code in enumerate(codes, 1):
                    logger.info(f"진행률: {idx}/{total_codes} ({idx/total_codes*100:.1f}%)")
                    
                    result = await self.search_and_download_by_classification(page, code)
                    self.results.append(result)
                    
                    if result['success']:
                        success_count += 1
                    
                    # 다음 검색을 위한 대기
                    await asyncio.sleep(3)
                
                # 5. 결과 요약
                logger.info(f"크롤링 완료: 전체 {total_codes}개 중 {success_count}개 성공")
                
                # 결과를 CSV로 저장
                results_df = pd.DataFrame(self.results)
                results_file = self.download_dir / f"classification_crawling_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
                results_df.to_csv(results_file, index=False, encoding='utf-8-sig')
                logger.info(f"결과 파일 저장: {results_file}")
                
            finally:
                # 브라우저 정리
                await context.close()
                await browser.close()
                
        except Exception as e:
            logger.error(f"크롤링 실행 중 오류: {e}")
            raise

async def main():
    """메인 실행 함수"""
    # 설정
    excel_file = "수가코드목록_1.xlsx"  # 수가코드 엑셀 파일
    classification_mapping_file = "수가코드_분류매핑.xlsx"  # 분류 매핑 엑셀 파일
    download_directory = "./downloads"   # 다운로드 디렉토리
    
    # 크롤러 실행
    crawler = HIRAClassificationCrawler(excel_file, classification_mapping_file, download_directory)
    await crawler.run()

if __name__ == "__main__":
    asyncio.run(main())