"""
HIRA 요양기관 업무포털 색인분류 트리 전체 탐색 크롤러
색인분류 트리를 완전히 탐색하여 모든 수가코드를 수집하고 다운로드
"""

import asyncio
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Set
import pandas as pd
from playwright.async_api import async_playwright, Page, Browser, BrowserContext, Locator

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('hira_full_tree_crawler.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class HIRAFullTreeCrawler:
    def __init__(self, download_dir: str = "./downloads"):
        """
        HIRA 색인분류 트리 전체 탐색 크롤러 초기화
        
        Args:
            download_dir: 다운로드 디렉토리 경로
        """
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(exist_ok=True)
        
        # HIRA 웹사이트 URL 및 CSS 선택자
        self.popup_url = "https://biz.hira.or.kr/popup.ndo?formname=qya_bizcom%3A%3AInfoBank.xfdl&framename=InfoBank"
        self.selectors = {
            'classification_search_btn': 'text=색인분류 검색',
            'search_button': '#InfoBank_form_divMain_divWork1_btnS0001',
            'excel_button': '#InfoBank_form_divMain_divWork1_btnE0001TextBoxElement',
            'search_input': '#InfoBank_form_divMain_divWork1_edtSearchTxt_input',
            'modal_close_btn': 'text=닫기'
        }
        
        # 수집된 분류 경로 및 결과 추적
        self.collected_paths: Set[str] = set()  # 중복 방지용
        self.results: List[Dict] = []
        self.total_downloads = 0
        
    async def setup_browser(self) -> tuple[Browser, BrowserContext, Page]:
        """브라우저 설정 및 페이지 생성"""
        playwright = await async_playwright().start()
        
        browser = await playwright.chromium.launch(
            headless=False,
            slow_mo=1000,  # 클릭 동작을 명확히 보기 위해 1초 대기
            args=['--disable-web-security', '--disable-features=VizDisplayCompositor']  # Nexacro 호환성
        )
        
        context = await browser.new_context(
            accept_downloads=True,
            viewport={'width': 1920, 'height': 1080}
        )
        
        page = await context.new_page()
        page.on('download', self._handle_download)
        
        return browser, context, page
    
    async def _handle_download(self, download):
        """다운로드 이벤트 핸들러"""
        try:
            self.total_downloads += 1
            filename = f"classification_{self.total_downloads:04d}_{int(time.time())}_{download.suggested_filename}"
            await download.save_as(self.download_dir / filename)
            logger.info(f"파일 다운로드 완료: {filename}")
        except Exception as e:
            logger.error(f"다운로드 처리 실패: {e}")
    
    async def debug_page_elements(self, page: Page):
        """페이지의 모든 버튼 요소를 디버깅용으로 출력한다."""
        try:
            logger.info("=== 페이지 디버깅 시작 ===")
            
            # 모든 버튼 요소 찾기
            buttons = await page.locator('button, input[type="button"], input[type="submit"], *[onclick]').all()
            logger.info(f"총 {len(buttons)}개의 클릭 가능 요소 발견")
            
            for i, btn in enumerate(buttons[:20]):  # 처음 20개만 출력
                try:
                    text = await btn.text_content()
                    tag_name = await btn.evaluate('el => el.tagName')
                    classes = await btn.get_attribute('class') or ''
                    onclick = await btn.get_attribute('onclick') or ''
                    title = await btn.get_attribute('title') or ''
                    value = await btn.get_attribute('value') or ''
                    
                    logger.info(f"[{i+1}] {tag_name} - Text: '{text}' | Class: '{classes}' | Title: '{title}' | Value: '{value}' | OnClick: '{onclick[:50]}...'")
                    
                    # 색인분류 관련 키워드 찾기
                    search_terms = ['색인', '분류', 'classification', 'index', '검색', 'search']
                    full_text = f"{text} {classes} {title} {value} {onclick}".lower()
                    
                    for term in search_terms:
                        if term in full_text:
                            logger.info(f"*** 색인분류 후보 발견: [{i+1}] '{term}' 포함 ***")
                            break
                            
                except Exception as e:
                    logger.debug(f"요소 [{i+1}] 분석 실패: {e}")
                    
            logger.info("=== 페이지 디버깅 종료 ===")
            
        except Exception as e:
            logger.error(f"페이지 디버깅 실패: {e}")
    
    async def open_classification_modal(self, page: Page) -> bool:
        """색인분류 검색 모달을 열다."""
        try:
            logger.info("색인분류 검색 모달 열기 시도...")
            
            # 디버깅: 페이지 요소 분석
            await self.debug_page_elements(page)
            
            # 확장된 색인분류 검색 버튼 선택자
            classification_selectors = [
                'text=색인분류 검색',
                'text=색인분류',
                'button:has-text("색인분류")',
                'button:has-text("색인")',
                'input[value*="색인분류"]',
                'input[value*="색인"]',
                '[title*="색인분류"]',
                '[title*="색인"]',
                '[onclick*="classification"]',
                '[onclick*="색인"]',
                '[onclick*="index"]',
                '*[class*="btn"]:has-text("색인")',
                'span:has-text("색인분류")',
                'div:has-text("색인분류")',
                'td:has-text("색인분류")',
                # Nexacro 특수 선택자
                '[nexacroid*="btn"][title*="색인"]',
                '[id*="btn"]:has-text("색인")',
                # 이미지 버튼일 경우
                'img[alt*="색인"]',
                'img[title*="색인"]'
            ]
            
            for i, selector in enumerate(classification_selectors):
                try:
                    logger.info(f"[선택자 {i+1}/{len(classification_selectors)}] 시도: {selector}")
                    
                    btn = page.locator(selector).first
                    
                    # 요소 존재 확인
                    if await btn.count() == 0:
                        logger.debug(f"선택자 '{selector}': 요소 없음")
                        continue
                    
                    # 요소 가시성 확인
                    if not await btn.is_visible():
                        logger.debug(f"선택자 '{selector}': 요소 비가시")
                        continue
                    
                    # 요소 활성화 대기
                    try:
                        await btn.wait_for(state='enabled', timeout=3000)
                    except:
                        logger.debug(f"선택자 '{selector}': 요소 비활성")
                        continue
                    
                    # 클릭 시도
                    await btn.click()
                    logger.info(f"색인분류 검색 버튼 클릭 성공: {selector}")
                    await asyncio.sleep(5)  # 모달 로딩 대기
                    return True
                    
                except Exception as e:
                    logger.debug(f"선택자 {selector} 시도 실패: {e}")
                    continue
            
            # 모든 선택자 실패 시 별도 전략
            logger.warning("기본 선택자로 버튼을 찾을 수 없음. 좌표 기반 클릭 시도...")
            return await self.try_coordinate_click(page)
            
        except Exception as e:
            logger.error(f"색인분류 모달 열기 실패: {e}")
            return False
    
    async def try_coordinate_click(self, page: Page) -> bool:
        """좌표 기반으로 색인분류 버튼 클릭 시도"""
        try:
            # 일반적인 버튼 위치들을 시도해보기
            button_coordinates = [
                (100, 100),   # 좌상단
                (200, 100),
                (300, 100),
                (100, 150),
                (200, 150),
                (300, 150),
                (100, 200),
                (200, 200),
                (300, 200)
            ]
            
            for x, y in button_coordinates:
                try:
                    logger.info(f"좌표 ({x}, {y}) 클릭 시도")
                    await page.click(f'body', position={'x': x, 'y': y})
                    await asyncio.sleep(2)
                    
                    # 모달이 열렸는지 확인 (기본적인 모달 요소 찾기)
                    modal_selectors = ['div[class*="modal"]', 'div[class*="popup"]', 'div[class*="dialog"]']
                    for modal_sel in modal_selectors:
                        if await page.locator(modal_sel).is_visible():
                            logger.info(f"좌표 ({x}, {y}) 클릭으로 모달 열기 성공")
                            return True
                            
                except Exception as e:
                    logger.debug(f"좌표 ({x}, {y}) 클릭 실패: {e}")
                    continue
            
            return False
            
        except Exception as e:
            logger.error(f"좌표 기반 클릭 실패: {e}")
            return False
    
    async def get_tree_elements(self, page: Page, level: str) -> List[Locator]:
        """
        트리에서 특정 레벨의 클릭 가능한 요소들을 가져온다.
        
        Args:
            page: Playwright 페이지
            level: 'major', 'middle', 'minor' 중 하나
            
        Returns:
            클릭 가능한 요소 리스트
        """
        try:
            # 다양한 선택자로 트리 요소 찾기
            tree_selectors = [
                'div[class*="tree"] span',
                'div[class*="node"] span',
                'td[class*="tree"]',
                'span[onclick]',
                'div[onclick]',
                'a[href*="#"]',
                '[class*="folder"]',
                '[class*="leaf"]'
            ]
            
            elements = []
            for selector in tree_selectors:
                try:
                    locators = page.locator(selector)
                    count = await locators.count()
                    
                    for i in range(count):
                        element = locators.nth(i)
                        if await element.is_visible():
                            # 텍스트가 있고 클릭 가능한 요소만 추가
                            text = await element.text_content()
                            if text and text.strip():
                                elements.append(element)
                    
                    if elements:
                        logger.info(f"트리 요소 {len(elements)}개 발견 (선택자: {selector})")
                        break
                        
                except Exception as e:
                    continue
            
            return elements
            
        except Exception as e:
            logger.error(f"트리 요소 가져오기 실패: {e}")
            return []
    
    async def explore_classification_tree(self, page: Page, path: List[str] = None) -> None:
        """
        색인분류 트리를 재귀적으로 탐색한다.
        
        Args:
            page: Playwright 페이지
            path: 현재까지의 분류 경로
        """
        if path is None:
            path = []
        
        try:
            current_level = len(path)
            level_names = ['대분류', '중분류', '소분류']
            
            if current_level >= 3:  # 소분류까지 도달
                path_str = ' → '.join(path)
                if path_str not in self.collected_paths:
                    self.collected_paths.add(path_str)
                    logger.info(f"분류 경로 완료: {path_str}")
                    
                    # 소분류 클릭 후 다운로드 시도
                    await self.process_final_classification(page, path)
                return
            
            logger.info(f"{level_names[current_level]} 탐색 중... (현재 경로: {' → '.join(path)})")
            
            # 현재 레벨의 요소들 가져오기
            elements = await self.get_tree_elements(page, level_names[current_level].lower())
            
            if not elements:
                logger.warning(f"{level_names[current_level]} 요소를 찾을 수 없습니다.")
                return
            
            # 각 요소를 순차적으로 클릭하여 탐색
            for i, element in enumerate(elements):
                try:
                    # 요소 텍스트 가져오기
                    element_text = await element.text_content()
                    if not element_text or not element_text.strip():
                        continue
                    
                    element_text = element_text.strip()
                    logger.info(f"{level_names[current_level]} [{i+1}/{len(elements)}]: '{element_text}' 클릭 시도")
                    
                    # 요소 클릭
                    await element.click()
                    await asyncio.sleep(2)  # 하위 요소 로딩 대기
                    
                    # 다음 레벨로 재귀 탐색
                    new_path = path + [element_text]
                    await self.explore_classification_tree(page, new_path)
                    
                    # 백트래킹: 상위 레벨로 돌아가기 위해 모달을 다시 열거나 상위 요소 클릭
                    if current_level < 2:  # 대분류, 중분류인 경우만 백트래킹
                        await self.reset_classification_state(page)
                    
                except Exception as e:
                    logger.error(f"요소 '{element_text}' 처리 중 오류: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"트리 탐색 중 오류 발생: {e}")
    
    async def reset_classification_state(self, page: Page) -> None:
        """분류 상태를 초기화하여 다른 분류를 탐색할 수 있도록 한다."""
        try:
            # 모달 닫기
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
                        await asyncio.sleep(1)
                        break
                except:
                    continue
            
            # 모달 다시 열기
            await asyncio.sleep(2)
            await self.open_classification_modal(page)
            
        except Exception as e:
            logger.error(f"분류 상태 초기화 실패: {e}")
    
    async def process_final_classification(self, page: Page, path: List[str]) -> Dict:
        """
        소분류까지 선택된 상태에서 조회 및 다운로드를 처리한다.
        
        Args:
            page: Playwright 페이지
            path: 분류 경로
            
        Returns:
            처리 결과
        """
        result = {
            'path': ' → '.join(path),
            'success': False,
            'error': None,
            'filename': None,
            'timestamp': datetime.now().isoformat()
        }
        
        try:
            logger.info(f"최종 분류 처리: {result['path']}")
            
            # 모달 닫기
            await self.close_classification_modal(page)
            
            # 검색창에 코드가 입력되었는지 확인
            await asyncio.sleep(2)
            search_input = page.locator(self.selectors['search_input'])
            input_value = await search_input.input_value()
            logger.info(f"검색창 입력값: '{input_value}'")
            
            if not input_value.strip():
                result['error'] = "검색창에 코드가 입력되지 않음"
                logger.warning(f"분류 '{result['path']}': 검색창이 비어있습니다.")
                return result
            
            # 조회 버튼 클릭
            search_button = page.locator(self.selectors['search_button'])
            await search_button.wait_for(state='visible', timeout=10000)
            await search_button.wait_for(state='enabled', timeout=5000)
            await search_button.click()
            
            logger.info("조회 버튼 클릭 완료")
            await asyncio.sleep(5)  # 조회 결과 로딩 대기
            
            # 엑셀 다운로드 시도
            try:
                excel_button = page.locator(self.selectors['excel_button'])
                await excel_button.wait_for(state='visible', timeout=10000)
                await excel_button.wait_for(state='enabled', timeout=5000)
                
                async with page.expect_download(timeout=30000) as download_info:
                    await excel_button.click()
                    
                download = await download_info.value
                
                # 파일명 생성
                safe_path = "_".join(path).replace("/", "_").replace("\\", "_")
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{safe_path}_{timestamp}_{download.suggested_filename}"
                filepath = self.download_dir / filename
                
                await download.save_as(filepath)
                
                result['success'] = True
                result['filename'] = filename
                logger.info(f"다운로드 성공: {filename}")
                
            except Exception as e:
                logger.warning(f"분류 '{result['path']}': 다운로드 불가 - {str(e)}")
                result['error'] = f"다운로드 불가: {str(e)}"
                
                # 조회 결과 없음 확인
                try:
                    no_data_msg = page.locator("text=조회된 데이터가 없습니다")
                    if await no_data_msg.is_visible():
                        result['error'] = "조회 결과 없음"
                        logger.info(f"분류 '{result['path']}': 조회 결과 없음")
                except:
                    pass
            
        except Exception as e:
            logger.error(f"분류 '{result['path']}' 처리 중 오류: {e}")
            result['error'] = str(e)
        
        # 결과 저장
        self.results.append(result)
        return result
    
    async def close_classification_modal(self, page: Page):
        """분류 모달을 닫는다."""
        try:
            close_selectors = [
                'button:has-text("닫기")',
                'button:has-text("확인")',
                'button:has-text("선택")',
                '[title="닫기"]',
                '.modal-close',
                '[class*="close"]'
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
    
    async def run(self):
        """크롤링 메인 실행 함수"""
        logger.info("HIRA 색인분류 트리 전체 탐색 시작")
        
        try:
            # 브라우저 설정
            browser, context, page = await self.setup_browser()
            
            try:
                # HIRA 팝업 페이지 접속
                logger.info(f"웹사이트 접속: {self.popup_url}")
                await page.goto(self.popup_url, wait_until='networkidle', timeout=30000)
                
                # Nexacro 애플리케이션 로딩 대기
                logger.info("Nexacro 애플리케이션 로딩 대기...")
                await asyncio.sleep(10)  # Nexacro 로딩 시간 여유 있게 대기
                
                # 페이지 완전 로딩 확인
                try:
                    # 기본 검색 입력창이 나타날 때까지 대기
                    search_input = page.locator(self.selectors['search_input'])
                    await search_input.wait_for(state='visible', timeout=15000)
                    logger.info("기본 페이지 로딩 완료")
                except:
                    logger.warning("기본 검색 입력창을 찾을 수 없음. 계속 진행...")
                
                await asyncio.sleep(3)  # 추가 안정화 대기
                
                # 색인분류 모달 열기
                if not await self.open_classification_modal(page):
                    logger.error("색인분류 모달 열기 실패")
                    return
                
                # 트리 전체 탐색 시작
                logger.info("색인분류 트리 전체 탐색을 시작합니다...")
                await self.explore_classification_tree(page)
                
                # 결과 요약
                total_paths = len(self.collected_paths)
                successful_downloads = sum(1 for r in self.results if r['success'])
                
                logger.info(f"탐색 완료:")
                logger.info(f"  - 발견된 분류 경로: {total_paths}개")
                logger.info(f"  - 성공한 다운로드: {successful_downloads}개")
                logger.info(f"  - 실패한 다운로드: {len(self.results) - successful_downloads}개")
                
                # 결과를 CSV로 저장
                if self.results:
                    results_df = pd.DataFrame(self.results)
                    results_file = self.download_dir / f"full_tree_crawling_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
                    results_df.to_csv(results_file, index=False, encoding='utf-8-sig')
                    logger.info(f"결과 파일 저장: {results_file}")
                
                # 수집된 분류 경로 저장
                paths_file = self.download_dir / f"collected_paths_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                with open(paths_file, 'w', encoding='utf-8') as f:
                    for path in sorted(self.collected_paths):
                        f.write(f"{path}\n")
                logger.info(f"분류 경로 파일 저장: {paths_file}")
                
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
    download_directory = "./downloads"
    
    crawler = HIRAFullTreeCrawler(download_directory)
    await crawler.run()

if __name__ == "__main__":
    asyncio.run(main())