"""
HIRA 요양기관 업무포털 수가코드 엑셀 다운로드 자동화 크롤러
Playwright MCP 기반으로 구현된 자동화 스크립트
"""

import asyncio
import logging
import os
import time
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
        logging.FileHandler('hira_crawler.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class HIRACrawler:
    def __init__(self, excel_file_path: str, download_dir: str = "./downloads"):
        """
        HIRA 크롤러 초기화
        
        Args:
            excel_file_path: 수가코드가 포함된 엑셀 파일 경로
            download_dir: 다운로드 디렉토리 경로
        """
        self.excel_file_path = excel_file_path
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(exist_ok=True)
        
        # HIRA 웹사이트 URL 및 CSS 선택자
        self.main_url = "https://biz.hira.or.kr/index.do"
        self.popup_url = "https://biz.hira.or.kr/popup.ndo?formname=qya_bizcom%3A%3AInfoBank.xfdl&framename=InfoBank"
        self.selectors = {
            'search_input': '#InfoBank_form_divMain_divWork1_edtSearchTxt_input',
            'search_button': '#InfoBank_form_divMain_divWork1_btnS0001',
            'excel_button': '#InfoBank_form_divMain_divWork1_btnE0001TextBoxElement'
        }
        
        # 다운로드 결과 추적
        self.results: List[Dict] = []
        
        # 세션 유지용 메인 페이지 참조
        self.main_page: Optional[Page] = None
        
    def read_excel_codes(self) -> List[str]:
        """
        엑셀 파일에서 수가코드 목록을 읽어온다.
        
        Returns:
            수가코드 리스트
        """
        try:
            # 엑셀 파일 읽기 (첫 번째 시트의 첫 번째 컬럼)
            df = pd.read_excel(self.excel_file_path)
            
            # 첫 번째 컬럼의 값들을 문자열로 변환하여 반환
            codes = df.iloc[:, 0].astype(str).tolist()
            
            # NaN 값이나 빈 값 제거
            codes = [code.strip() for code in codes if pd.notna(code) and str(code).strip()]
            
            logger.info(f"엑셀 파일에서 {len(codes)}개의 수가코드를 읽었습니다.")
            return codes
            
        except Exception as e:
            logger.error(f"엑셀 파일 읽기 실패: {e}")
            raise
    
    async def setup_browser(self) -> tuple[Browser, BrowserContext]:
        """
        브라우저 설정 및 컨텍스트 생성
        
        Returns:
            browser, context 튜플
        """
        playwright = await async_playwright().start()
        
        # 브라우저 실행 옵션
        browser = await playwright.chromium.launch(
            headless=False,  # 디버깅을 위해 GUI 모드로 실행
            slow_mo=1000     # 동작 간 1초 대기
        )
        
        # 브라우저 컨텍스트 생성 (다운로드 설정 포함)
        context = await browser.new_context(
            accept_downloads=True,
            viewport={'width': 1920, 'height': 1080}
        )
        
        # 다운로드 경로 설정
        await context.set_extra_http_headers({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
        return browser, context
    
    async def _handle_download(self, download):
        """
        다운로드 이벤트 핸들러
        
        Args:
            download: 다운로드 객체
        """
        try:
            # 다운로드 완료 대기
            await download.save_as(
                self.download_dir / f"temp_{int(time.time())}_{download.suggested_filename}"
            )
            logger.info(f"파일 다운로드 완료: {download.suggested_filename}")
        except Exception as e:
            logger.error(f"다운로드 처리 실패: {e}")
    
    async def ensure_popup_page(self, context: BrowserContext, popup_page: Optional[Page] = None) -> Page:
        """
        팝업 페이지가 닫혔는지 확인하고 필요시 재접속
        
        Args:
            context: 브라우저 컨텍스트
            popup_page: 기존 팝업 페이지 (None이면 새로 생성)
            
        Returns:
            유효한 팝업 페이지 객체
        """
        # 기존 팝업 페이지가 있고 아직 열려있다면 그대로 반환
        if popup_page is not None and not popup_page.is_closed():
            return popup_page
            
        if popup_page is not None and popup_page.is_closed():
            logger.warning("팝업 페이지가 닫혔습니다. 재접속을 시도합니다.")
            
        return await self.open_popup_page(context)
    
    async def open_popup_page(self, context: BrowserContext) -> Page:
        """
        메인 페이지에서 팝업을 열거나 직접 팝업 페이지에 접속
        
        Args:
            context: 브라우저 컨텍스트
            
        Returns:
            팝업 페이지 객체
        """
        try:
            # 방법 1: 메인 페이지에서 팝업 열기 시도
            if self.main_page is None or self.main_page.is_closed():
                self.main_page = await context.new_page()
            main_page = self.main_page
            logger.info(f"메인 페이지 접속: {self.main_url}")
            await main_page.goto(self.main_url, wait_until='networkidle', timeout=30000)
            await asyncio.sleep(3)
            
            # 심사기준 종합서비스 또는 색인분류 검색 메뉴 찾기
            menu_selectors = [
                "text=심사기준 종합서비스",
                "text=색인분류 검색",
                "text=InfoBank",
                "[onclick*='InfoBank']",
                "a[href*='InfoBank']"
            ]
            
            popup_page = None
            for selector in menu_selectors:
                try:
                    menu_link = main_page.locator(selector)
                    if await menu_link.is_visible():
                        logger.info(f"메뉴 링크 발견: {selector}")
                        
                        # 팝업 페이지가 열릴 것을 기대
                        async with context.expect_page() as popup_info:
                            await menu_link.click()
                            
                        popup_page = await popup_info.value
                        await popup_page.wait_for_load_state('networkidle', timeout=30000)
                        
                        # 팝업 페이지가 완전히 로딩될 때까지 추가 대기
                        await asyncio.sleep(3)
                        
                        # 검색 입력창이 나타날 때까지 대기하여 팝업이 정상 작동하는지 확인
                        try:
                            search_input = popup_page.locator(self.selectors['search_input'])
                            await search_input.wait_for(state='visible', timeout=10000)
                            logger.info("팝업 페이지가 성공적으로 열렸습니다.")
                            break
                        except:
                            # 검색창이 나타나지 않으면 이 팝업은 실패한 것으로 간주
                            await popup_page.close()
                            popup_page = None
                            continue
                        
                except Exception as e:
                    logger.debug(f"메뉴 선택자 {selector} 시도 실패: {e}")
                    continue
            
            # Nexacro 기반 웹사이트는 팝업이 메인 세션에 의존하므로 메인 페이지를 닫지 않음
            # 팝업이 열리지 않았을 때만 메인 페이지 정리
            if popup_page is None:
                await main_page.close()
                logger.info("팝업 열기 실패로 메인 페이지를 닫았습니다.")
            else:
                logger.info("Nexacro 세션 유지를 위해 메인 페이지를 열린 상태로 유지합니다.")
            
            # 방법 1이 실패했다면 방법 2: 직접 팝업 URL 접속
            if popup_page is None:
                logger.info("메뉴에서 팝업 열기 실패, 직접 팝업 URL로 접속")
                popup_page = await context.new_page()
                
                # referer 설정하여 팝업 URL 접속
                await popup_page.goto(self.popup_url, 
                                    wait_until='networkidle', 
                                    timeout=30000,
                                    referer=self.main_url)
            
            # 다운로드 이벤트 리스너 추가
            popup_page.on('download', self._handle_download)
            
            return popup_page
            
        except Exception as e:
            logger.error(f"팝업 페이지 열기 실패: {e}")
            raise
    
    async def search_and_download(self, context: BrowserContext, page: Page, code: str) -> Dict:
        """
        특정 수가코드로 검색하고 엑셀 파일을 다운로드한다.
        
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
            logger.info(f"수가코드 '{code}' 처리 시작")
            
            # 팝업 페이지 상태 확인 및 재접속
            try:
                page = await self.ensure_popup_page(context, page)
            except Exception as e:
                logger.error(f"팝업 페이지 확인/재접속 실패: {e}")
                result['error'] = f"팝업 페이지 접근 실패: {str(e)}"
                return result
            
            # 1. 검색 입력창에 수가코드 입력
            search_input = page.locator(self.selectors['search_input'])
            await search_input.wait_for(state='visible', timeout=10000)
            
            # 기존 텍스트 지우고 새 코드 입력
            await search_input.clear()
            await search_input.fill(code)
            await asyncio.sleep(0.5)
            
            logger.info(f"검색어 입력 완료: {code}")
            
            # 2. 조회 버튼 클릭
            search_button = page.locator(self.selectors['search_button'])
            await search_button.wait_for(state='visible', timeout=10000)
            
            # 버튼이 활성화될 때까지 대기
            await search_button.wait_for(state='enabled', timeout=5000)
            await search_button.click()
            
            logger.info("조회 버튼 클릭 완료")
            
            # 3. 로딩 대기 (조회 결과가 나타날 때까지)
            await asyncio.sleep(3)
            
            # 4. 엑셀 저장 버튼 확인 및 클릭
            excel_button = page.locator(self.selectors['excel_button'])
            
            try:
                # 엑셀 버튼이 나타나고 활성화될 때까지 대기
                await excel_button.wait_for(state='visible', timeout=10000)
                await excel_button.wait_for(state='enabled', timeout=5000)
                
                # 다운로드 시작 전 기존 다운로드 수 확인
                downloads_before = len(list(self.download_dir.glob("*")))
                
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
                # 엑셀 버튼이 비활성화되어 있거나 조회 결과가 없는 경우
                logger.warning(f"수가코드 '{code}': 다운로드 불가 - {str(e)}")
                result['error'] = f"다운로드 불가: {str(e)}"
                
                # 조회 결과가 없는지 확인
                try:
                    # Nexacro 기반 웹사이트에서 "조회된 데이터가 없습니다" 메시지 확인
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
        """
        크롤링 메인 실행 함수
        """
        logger.info("HIRA 수가코드 크롤링 시작")
        
        try:
            # 1. 엑셀 파일에서 수가코드 읽기
            codes = self.read_excel_codes()
            
            if not codes:
                logger.error("수가코드가 없습니다.")
                return
            
            # 2. 브라우저 설정
            browser, context = await self.setup_browser()
            
            try:
                # 3. 팝업 페이지 열기
                page = await self.open_popup_page(context)
                
                # 4. 각 수가코드별 처리
                total_codes = len(codes)
                success_count = 0
                
                for idx, code in enumerate(codes, 1):
                    logger.info(f"진행률: {idx}/{total_codes} ({idx/total_codes*100:.1f}%)")
                    
                    result = await self.search_and_download(context, page, code)
                    self.results.append(result)
                    
                    
                    if result['success']:
                        success_count += 1
                    
                    # 다음 검색을 위한 대기
                    await asyncio.sleep(2)
                
                # 5. 결과 요약
                logger.info(f"크롤링 완료: 전체 {total_codes}개 중 {success_count}개 성공")
                
                # 결과를 CSV로 저장
                results_df = pd.DataFrame(self.results)
                results_file = self.download_dir / f"crawling_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
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
    """
    메인 실행 함수
    """
    # 설정
    excel_file = "수가코드목록_1.xlsx"  # 엑셀 파일 경로
    download_directory = "./downloads"   # 다운로드 디렉토리
    
    # 크롤러 실행
    crawler = HIRACrawler(excel_file, download_directory)
    await crawler.run()

if __name__ == "__main__":
    # 이벤트 루프 실행
    asyncio.run(main())