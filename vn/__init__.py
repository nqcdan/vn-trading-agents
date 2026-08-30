from .env import load_dotenv

load_dotenv()  # nạp .env ở root repo vào os.environ (trước khi các module đọc env)

from . import vn_market, vn_data, vn_news, agents, vn_backtest, portfolio  # noqa: E402,F401
