import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock
from search_terms import search_terms
from goofish_monitor import GoofishMonitor
from monitor_service import MonitorService


class TermsTest(unittest.TestCase):
    def test_delimiters_spaces_duplicates(self):
        self.assertEqual(search_terms(' OWC 1M2，OWC USB4,owc 1m2\nOWC Express 1M2\r\n, '), ['OWC 1M2', 'OWC USB4', 'OWC Express 1M2'])
        self.assertEqual(search_terms('OWC Express 1M2'), ['OWC Express 1M2'])

    def test_limits_and_empty(self):
        for value in ['', ',，\n', 'x'*81, ','.join(str(i) for i in range(21)), None]:
            with self.assertRaises(ValueError): search_terms(value)


class MultiSearchTest(unittest.IsolatedAsyncioTestCase):
    async def test_independent_queries_share_filters_and_deduplicate_item(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'config.json'
            product={'name':'硬盘盒','keyword':'OWC 1M2，OWC USB4\nOWC 1M2','min_price':600,'target_price':800,'min_score':50,'max_results':20}
            path.write_text(json.dumps({'products':[product]}))
            m=GoofishMonitor(path); m.human_delay=AsyncMock()
            queries=[]
            async def check(page, rule):
                queries.append(rule)
                candidate=m.evaluate_item({'item_id':'123','title':'OWC 1M2','price':799,'href':'https://www.goofish.com/item?id=123'},rule)
                return [candidate] if candidate else []
            m.check_product=check
            results=await m.run_round(None)
            self.assertEqual([x['keyword'] for x in queries],['OWC 1M2','OWC USB4'])
            self.assertTrue(all(x['min_price']==600 and x['max_results']==20 for x in queries))
            self.assertEqual(len(results),1)
            self.assertEqual(m.products[0]['keyword'],product['keyword'])

    async def test_login_verification_uses_one_search_phrase(self):
        with tempfile.TemporaryDirectory() as d:
            service=MonitorService(Path(d)/'config.json')
            monitor=Mock(products=[{'keyword':'OWC 1M2，OWC USB4'}])
            monitor.assert_page_usable=AsyncMock()
            response=Mock();response.json=AsyncMock(return_value={'ret':['SUCCESS'],'data':{'resultList':[]}})
            monitor.goto_and_capture_search=AsyncMock(return_value=response)
            await service.verified_search(monitor,None)
            self.assertTrue(monitor.goto_and_capture_search.call_args.args[1].endswith('q=OWC+1M2'))
