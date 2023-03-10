import pytest
from brownie import chain, Wei, reverts, Contract, ZERO_ADDRESS

# try and figure out how to make this live in conftest and call it from multiple different test files
def move_funds(
    vault,
    dest_vault,
    strategy,
    gov,
    token,
    whale,
    RELATIVE_APPROX,
):
    print(strategy.name())

    strategy.harvest({"from": gov})
    assert strategy.balanceOfWant() == 0
    assert strategy.valueOfInvestment() > 0
    chain.sleep(1)
    chain.mine(1)

    prev_value = strategy.valueOfInvestment()

    # have to harvest strategy to queue that profit in 0.4.6, donations to vault don't work, turn off health check
    destination_strategy = Contract("0x83D0458e627cFD7C6d0da12a1223bd168e1c8B64")
    token.transfer(destination_strategy, Wei("10_000 ether"), {"from": whale})
    dest_pps = dest_vault.pricePerShare()
    print("Destination PPS:", dest_pps / 1e18)
    destination_strategy.setDoHealthCheck(False, {"from": gov})
    tx = destination_strategy.harvest({"from": gov})
    chain.sleep(3600)
    chain.mine(10)
    dest_pps = dest_vault.pricePerShare()
    print("Destination PPS:", dest_pps / 1e18)
    print("Harvest Profit:", tx.events["Harvested"]["profit"])

    assert strategy.valueOfInvestment() > prev_value

    strategy.harvest({"from": gov})
    chain.sleep(3600 * 11)
    chain.mine(1)

    total_gain = vault.strategies(strategy).dict()["totalGain"]
    assert total_gain > 0
    assert vault.strategies(strategy).dict()["totalLoss"] == 0

    vault.revokeStrategy(strategy, {"from": gov})
    tx = strategy.harvest({"from": gov})
    total_gain += tx.events["Harvested"]["profit"]
    chain.sleep(3600 * 8)
    chain.mine(1)

    assert (
        pytest.approx(
            vault.strategies(strategy).dict()["totalGain"], rel=RELATIVE_APPROX
        )
        == total_gain
    )
    assert (
        pytest.approx(
            vault.strategies(strategy).dict()["totalLoss"], rel=RELATIVE_APPROX
        )
        == 0
    )
    assert (
        pytest.approx(
            vault.strategies(strategy).dict()["totalDebt"], rel=RELATIVE_APPROX
        )
        == 0
    )


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
):

    move_funds(
        origin_vault,
        destination_vault,
        strategy,
        gov,
        token,
        whale,
        RELATIVE_APPROX,
    )


def test_cloned_strategy(
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
):

    clone_tx = strategy.cloneRouter(
        origin_vault, strategist, rewards, keeper, destination_vault, "ClonedStrategy"
    )

    cloned_strategy = Contract.from_abi(
        "Strategy", clone_tx.events["Cloned"]["clone"], strategy.abi
    )

    origin_vault.updateStrategyDebtRatio(strategy, 0, {"from": gov})

    # Return the funds to the vault
    strategy.harvest({"from": gov})
    origin_vault.addStrategy(cloned_strategy, 10_000, 0, 2**256 - 1, 0, {"from": gov})

    move_funds(
        origin_vault,
        destination_vault,
        cloned_strategy,
        gov,
        token,
        whale,
        RELATIVE_APPROX,
    )


def test_clone_of_clone(
    origin_vault, destination_vault, strategist, rewards, keeper, strategy
):

    clone_tx = strategy.cloneRouter(
        origin_vault, strategist, rewards, keeper, destination_vault, "ClonedStrategy"
    )

    cloned_strategy = Contract.from_abi(
        "Strategy", clone_tx.events["Cloned"]["clone"], strategy.abi
    )

    # should not clone a clone
    with reverts():
        cloned_strategy.cloneRouter(
            origin_vault,
            strategist,
            rewards,
            keeper,
            destination_vault,
            "New Strategy",
            {"from": strategist},
        )


def test_double_initialize(
    origin_vault, destination_vault, strategist, rewards, keeper, strategy
):

    clone_tx = strategy.cloneRouter(
        origin_vault, strategist, rewards, keeper, destination_vault, "ClonedStrategy"
    )

    cloned_strategy = Contract.from_abi(
        "Strategy", clone_tx.events["Cloned"]["clone"], strategy.abi
    )

    # should not be able to call initialize twice
    with reverts("Strategy already initialized"):
        cloned_strategy.initialize(
            origin_vault,
            strategist,
            rewards,
            keeper,
            destination_vault,
            "name",
            {"from": strategist},
        )
