import brownie
from brownie import Contract
from brownie import config
from utils import strategy_harvest

# test the our strategy's ability to deposit, harvest, and withdraw, with different optimal deposit tokens if we have them
def test_original_strategy(
    origin_vault,
    destination_vault,
    strategy,
    strategist,
    rewards,
    keeper,
    gov,
    token,
    whale,
    RELATIVE_APPROX,
    strategy_harvest,
):

    tx = strategy_harvest
