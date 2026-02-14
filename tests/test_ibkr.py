import shutil
import unittest
from pathlib import Path
from datetime import datetime
from unittest.mock import patch, MagicMock

# Import the module to test
import ibkr

class TestIBKRSync(unittest.TestCase):
    def setUp(self):
        # Setup a temporary data directory for testing
        self.test_dir = Path("./test_data_env")
        self.test_dir.mkdir(exist_ok=True)
        self.archive_dir = self.test_dir / "Archive"
        
        # Patch DATA_DIR in the ibkr module to point to our temp dir
        self.patcher = patch("ibkr.DATA_DIR", self.test_dir)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)

    @patch("ibkr.download_flex_report")
    @patch("ibkr.parse_csv_trades")
    def test_sync_ibkr_trades(self, mock_parse, mock_download):
        # 1. Setup scenario
        current_year = datetime.now().year
        prev_year = current_year - 1
        
        ytd_filename = f"{current_year}_YTD.csv"
        ytd_path = self.test_dir / ytd_filename
        prev_fy_filename = f"{prev_year}_FY.csv"
        prev_fy_path = self.test_dir / prev_fy_filename
        
        # Create dummy existing files
        ytd_path.write_text("old ytd data")
        prev_fy_path.write_text("prev year data")
        
        # Mock download to simulate getting a new file
        mock_download.return_value = ytd_path
        
        # 2. Execute
        ibkr.sync_ibkr_trades()
        
        # 3. Assertions
        
        # Check archiving: The old YTD should have been moved to Archive
        archived_files = list(self.archive_dir.glob(f"{current_year}_YTD_*.csv"))
        self.assertEqual(len(archived_files), 1, "Should have archived exactly one YTD file")
        
        # Check download call
        mock_download.assert_called_once_with(ibkr.IBKR_QUERY_ID_TRADES, ytd_path, force_download=True)
        
        # Check parsing calls
        # Should be called for prev_year_FY and then the new current_year_YTD
        self.assertEqual(mock_parse.call_count, 2)
        
        # Verify specific paths passed to parser
        called_paths = [call.args[0] for call in mock_parse.call_args_list]
        self.assertIn(prev_fy_path, called_paths)
        self.assertIn(ytd_path, called_paths)

if __name__ == "__main__":
    unittest.main()
