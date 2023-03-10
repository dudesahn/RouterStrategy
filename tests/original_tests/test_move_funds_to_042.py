import pytest
from brownie import Contract, ZERO_ADDRESS, Wei, chain


def test_move_funds_to_042(
    curve_susd_035,
    curve_susd_045,
    unique_strategy,
    gov,
    token,
    whale,
    RELATIVE_APPROX,
):

    strategy = unique_strategy
    print(strategy.name())

    strategy.harvest({"from": gov})
    assert strategy.balanceOfWant() == 0
    assert strategy.valueOfInvestment() > 0

    # Send profit to 042
    prev_value = strategy.valueOfInvestment()
    token.transfer(curve_susd_045, Wei("10_000 ether"), {"from": whale})
    assert strategy.valueOfInvestment() > prev_value

    strategy.harvest({"from": gov})
    chain.sleep(3600 * 11)
    chain.mine(1)

    total_gain = curve_susd_035.strategies(strategy).dict()["totalGain"]
    assert total_gain > 0
    assert curve_susd_035.strategies(strategy).dict()["totalLoss"] == 0

    curve_susd_035.revokeStrategy(strategy, {"from": gov})
    tx = strategy.harvest({"from": gov})
    total_gain += tx.events["Harvested"]["profit"]
    chain.sleep(3600 * 8)
    chain.mine(1)

    assert (
        pytest.approx(
            curve_susd_035.strategies(strategy).dict()["totalGain"],
            rel=RELATIVE_APPROX,
        )
        == total_gain
    )
    assert (
        pytest.approx(
            curve_susd_035.strategies(strategy).dict()["totalLoss"],
            rel=RELATIVE_APPROX,
        )
        == 0
    )
    assert (
        pytest.approx(
            curve_susd_035.strategies(strategy).dict()["totalDebt"],
            rel=RELATIVE_APPROX,
        )
        == 0
    )
