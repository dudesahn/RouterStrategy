import brownie
from brownie import Contract
from brownie import config
import math

# test changing the debtRatio on a strategy and then harvesting it
def test_change_debt(
    gov,
    token,
    vault,
    strategist,
    whale,
    strategy,
    chain,
    amount,
    sleep_time,
    is_slippery,
    no_profit,
    strategy_harvest,
):
    ## deposit to the vault after approving
    startingWhale = token.balanceOf(whale)
    token.approve(vault, 2**256 - 1, {"from": whale})
    vault.deposit(amount, {"from": whale})
    harvest_tx = strategy_harvest()

    # evaluate our current total assets
    old_assets = vault.totalAssets()
    startingStrategy = strategy.estimatedTotalAssets()

    # debtRatio is in BPS (aka, max is 10,000, which represents 100%), and is a fraction of the funds that can be in the strategy
    currentDebt = vault.strategies(strategy)["debtRatio"]
    vault.updateStrategyDebtRatio(strategy, currentDebt / 2, {"from": gov})
    chain.sleep(sleep_time)
    harvest_tx = strategy_harvest()

    assert strategy.estimatedTotalAssets() <= startingStrategy

    # simulate one day of earnings
    chain.sleep(sleep_time)
    chain.mine(1)

    # set DebtRatio back to 100%
    vault.updateStrategyDebtRatio(strategy, currentDebt, {"from": gov})
    harvest_tx = strategy_harvest()

    # evaluate our current total assets
    new_assets = vault.totalAssets()

    # confirm we made money, or at least that we have about the same
    assert new_assets >= old_assets or math.isclose(new_assets, old_assets, abs_tol=5)

    # simulate five days of waiting for share price to bump back up
    chain.sleep(86400 * 5)
    chain.mine(1)

    # withdraw and confirm we made money, or at least that we have about the same (profit whale has to be different from normal whale)
    vault.withdraw({"from": whale})
    if is_slippery and no_profit:
        assert (
            math.isclose(token.balanceOf(whale), startingWhale, abs_tol=10)
            or token.balanceOf(whale) >= startingWhale
        )
    else:
        assert token.balanceOf(whale) >= startingWhale
