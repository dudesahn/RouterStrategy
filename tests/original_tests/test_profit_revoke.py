import pytest
from brownie import Contract, ZERO_ADDRESS, Wei, chain


def test_profit_revoke(
    curve_susd_035, curve_susd_045, unique_strategy, gov, token, whale
):

    strategy = unique_strategy
    strategy.harvest({"from": gov})
    assert strategy.balanceOfWant() == 0
    assert strategy.valueOfInvestment() > 0

    # Send profit to 045
    prev_value = strategy.valueOfInvestment()
    token.transfer(curve_susd_045, Wei("20_000 ether"), {"from": whale})
    assert strategy.valueOfInvestment() > prev_value

    curve_susd_035.revokeStrategy(strategy, {"from": gov})
    strategy.harvest({"from": gov})
    chain.sleep(3600 * 8)
    chain.mine(1)

    total_gain = curve_susd_035curve_susd_035.strategies(strategy).dict()["totalGain"]
    assert total_gain > 0
    assert curve_susd_035.strategies(strategy).dict()["totalLoss"] == 0
    assert strategy.balanceOfWant() == 0
    assert strategy.valueOfInvestment() < Wei("0.001 ether")  # there might be dust
