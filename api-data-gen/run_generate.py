#!/usr/bin/env python
import sys
sys.path.insert(0, 'src')

from api_data_gen.cli.main import main

if __name__ == "__main__":
    sys.argv = [
        'main.py',
        'generate',
        '--requirement-file', './requirements/test_wst_alert.txt',
        '--api', 'custTransInfo=/wst/custTransInfo',
        '--api', 'custDrftRecord=/wst/custDrftRecord',
        '--strategy-mode', 'agent_auto',
    ]
    main()
