import brownie
from brownie import Contract, chain, ZERO_ADDRESS
import pytest
from utils import harvest_strategy, check_status

# this module includes other tests we may need to generate, for instance to get best possible coverage on prepareReturn or liquidatePosition
# do any extra testing here to hit all parts of liquidatePosition
# generally this involves sending away all assets and then withdrawing before another harvest
def test_liquidatePosition(
    gov,
    token,
    vault,
    whale,
    strategy,
    amount,
    profit_whale,
    profit_amount,
    destination_strategy,
    use_yswaps,
    destination_vault,
):
    ## deposit to the vault after approving
    starting_whale = token.balanceOf(whale)
    token.approve(vault, 2 ** 256 - 1, {"from": whale})
    vault.deposit(amount, {"from": whale})
    (profit, loss) = harvest_strategy(
        use_yswaps,
        strategy,
        token,
        gov,
        profit_whale,
        profit_amount,
        destination_strategy,
    )

    ################# SEND ALL FUNDS AWAY. ADJUST AS NEEDED PER STRATEGY. #################
    to_send = destination_vault.balanceOf(strategy)
    destination_vault.transfer(gov, to_send, {"from": strategy})

    # confirm we emptied the strategy
    assert strategy.estimatedTotalAssets() == 0

    # withdraw and see how down bad we are, confirm we can withdraw from an empty vault
    # it's important to do this before harvesting, also allow max loss
    vault.withdraw(vault.balanceOf(whale), whale, 10_000, {"from": whale})


# there also may be situations where the destination protocol is exploited or funds are locked but you still hold the same number of wrapper tokens
# though liquity doesn't have this as an option, it's important to test if it is to make sure debt is maintained properly in the case future assets free up
def test_locked_funds(
    gov,
    token,
    vault,
    whale,
    strategy,
    amount,
    is_slippery,
    no_profit,
    sleep_time,
    profit_whale,
    profit_amount,
    destination_strategy,
    use_yswaps,
    old_vault,
    destination_vault,
):
    # should update this one for Router
    print("No way to test this for current strategy")


# here we take a loss intentionally without entering emergencyExit
def test_rekt(
    gov,
    token,
    vault,
    whale,
    strategy,
    amount,
    profit_whale,
    profit_amount,
    destination_strategy,
    use_yswaps,
    old_vault,
    destination_vault,
):
    ## deposit to the vault after approving
    starting_whale = token.balanceOf(whale)
    token.approve(vault, 2 ** 256 - 1, {"from": whale})
    vault.deposit(amount, {"from": whale})
    (profit, loss) = harvest_strategy(
        use_yswaps,
        strategy,
        token,
        gov,
        profit_whale,
        profit_amount,
        destination_strategy,
    )

    ################# SEND ALL FUNDS AWAY. ADJUST AS NEEDED PER STRATEGY. #################
    to_send = destination_vault.balanceOf(strategy)
    destination_vault.transfer(gov, to_send, {"from": strategy})

    # confirm we emptied the strategy
    assert strategy.estimatedTotalAssets() == 0

    # our whale donates 5 wei to the vault so we don't divide by zero (needed for older vaults)
    if old_vault:
        token.transfer(strategy, 5, {"from": whale})

    # set debtRatio to zero so we try and pull everything that we can out. turn off health check because of massive losses
    vault.updateStrategyDebtRatio(strategy, 0, {"from": gov})
    strategy.setDoHealthCheck(False, {"from": gov})
    (profit, loss) = harvest_strategy(
        use_yswaps,
        strategy,
        token,
        gov,
        profit_whale,
        profit_amount,
        destination_strategy,
    )
    # assert strategy.estimatedTotalAssets() == 0

    if old_vault:
        assert vault.totalAssets() == 5
    else:
        assert vault.totalAssets() == 0

    # simulate 5 days of waiting for share price to bump back up
    chain.sleep(86400 * 5)
    chain.mine(1)

    # withdraw and see how down bad we are, confirm we can withdraw from an empty vault
    vault.withdraw({"from": whale})

    print(
        "Raw loss:",
        (starting_whale - token.balanceOf(whale)) / 1e18,
        "Percentage:",
        (starting_whale - token.balanceOf(whale)) / starting_whale,
    )
    print("Share price:", vault.pricePerShare() / 1e18)


def test_weird_reverts(
    gov,
    token,
    vault,
    whale,
    strategy,
    destination_strategy,
):

    # only vault can call this
    with brownie.reverts():
        strategy.migrate(whale, {"from": gov})

    # can't migrate to a different vault
    with brownie.reverts():
        vault.migrateStrategy(strategy, destination_strategy, {"from": gov})

    # can't withdraw from a non-vault address
    with brownie.reverts():
        strategy.withdraw(1e18, {"from": gov})


# this test makes sure we can still harvest without any assets but still get our profits
# can also test here whether we claim rewards from an empty strategy, some protocols will revert
def test_empty_strat(
    gov,
    token,
    vault,
    whale,
    strategy,
    amount,
    profit_whale,
    profit_amount,
    destination_strategy,
    use_yswaps,
    destination_vault,
    old_vault,
    is_slippery,
    RELATIVE_APPROX,
    vault_address,
):
    ## deposit to the vault after approving
    starting_whale = token.balanceOf(whale)
    token.approve(vault, 2 ** 256 - 1, {"from": whale})
    vault.deposit(amount, {"from": whale})
    (profit, loss) = harvest_strategy(
        use_yswaps,
        strategy,
        token,
        gov,
        profit_whale,
        profit_amount,
        destination_strategy,
    )

    # store this for testing later
    starting_strategy_assets = strategy.estimatedTotalAssets()

    # check that our losses are approximately the whole strategy
    print("\nBefore any losses")
    check_status(strategy, vault)

    ################# SEND ALL FUNDS AWAY. ADJUST AS NEEDED PER STRATEGY. #################
    to_send = destination_vault.balanceOf(strategy)
    destination_vault.transfer(gov, to_send, {"from": strategy})

    # confirm we emptied the strategy
    assert strategy.estimatedTotalAssets() == 0

    # check that our losses are approximately the whole strategy
    print("\nAfter loss but before harvest")
    check_status(strategy, vault)

    if not old_vault:
        total_idle = vault.totalIdle()
        assert total_idle == 0

    if is_slippery:
        assert (
            pytest.approx(vault_assets, rel=RELATIVE_APPROX) == starting_strategy_assets
        )
        assert (
            pytest.approx(total_debt, rel=RELATIVE_APPROX) == starting_strategy_assets
        )
        assert (
            pytest.approx(strategy_debt, rel=RELATIVE_APPROX)
            == starting_strategy_assets
        )
    else:
        assert vault_assets == starting_strategy_assets
        assert total_debt == starting_strategy_assets
        assert strategy_debt == starting_strategy_assets

    assert debt_outstanding == 0
    assert share_price >= 10 ** token.decimals()
    assert strategy_loss == 0
    assert strategy_gain == 0
    assert strategy_debt_ratio == 10_000

    # our whale donates 5 wei to the vault so we don't divide by zero (needed for older vaults)
    if old_vault:
        token.transfer(strategy, 5, {"from": whale})

    # accept our losses, sad day 🥲
    strategy.setDoHealthCheck(False, {"from": gov})
    (profit, loss) = harvest_strategy(
        use_yswaps,
        strategy,
        token,
        gov,
        profit_whale,
        profit_amount,
        destination_strategy,
    )
    assert loss > 0

    # check our status
    print("\nAfter our big time loss")
    check_status(strategy, vault)

    if not old_vault:
        total_idle = vault.totalIdle()
        assert total_idle == 0

    if is_slippery:
        assert pytest.approx(vault_assets, rel=RELATIVE_APPROX) == 0
        assert (
            pytest.approx(total_debt, rel=RELATIVE_APPROX) == starting_strategy_assets
        )
        assert (
            pytest.approx(strategy_debt, rel=RELATIVE_APPROX)
            == starting_strategy_assets
        )
    else:
        assert vault_assets == 0
        assert total_debt == starting_strategy_assets
        assert strategy_debt == starting_strategy_assets

    # if it's an existing vault, just make sure share price went down. should be below 1 for new vaults
    if vault_address == ZERO_ADDRESS:
        assert vault.pricePerShare() < 10 ** token.decimals()
    else:
        assert vault.pricePerShare() < share_price

    assert debt_outstanding == 0
    assert strategy_loss == starting_strategy_assets
    assert strategy_gain == 0
    assert strategy_debt_ratio == 0

    # some profits fall from the heavens
    # this should be used to pay down debt vs taking profits
    token.transfer(strategy, profit_amount, {"from": profit_whale})
    strategy.setDoHealthCheck(False, {"from": gov})
    (profit, loss) = harvest_strategy(
        use_yswaps,
        strategy,
        token,
        gov,
        profit_whale,
        profit_amount,
        destination_strategy,
    )
    assert profit > 0
    share_price = vault.pricePerShare()
    assert share_price > 0
    print("Share price:", share_price)


# this test makes sure we can still harvest without any profit and not revert
# for some strategies it may be impossible to harvest without generating profit, especially if not using yswaps
def test_no_profit(
    gov,
    token,
    vault,
    whale,
    strategy,
    amount,
    profit_whale,
    profit_amount,
    destination_strategy,
    use_yswaps,
    sleep_time,
):
    ## deposit to the vault after approving
    token.approve(vault, 2 ** 256 - 1, {"from": whale})
    vault.deposit(amount, {"from": whale})
    (profit, loss) = harvest_strategy(
        use_yswaps,
        strategy,
        token,
        gov,
        profit_whale,
        profit_amount,
        destination_strategy,
    )

    # sleep
    chain.sleep(sleep_time)

    # check our current status
    print("\Before harvest")
    check_status(strategy, vault)

    # if are using yswaps and we don't want profit, don't use yswaps (False for first argument).
    # Or just don't harvest our destination strategy, can pass 0 for profit_amount and use if statement in utils
    (profit, loss) = harvest_strategy(
        use_yswaps,
        strategy,
        token,
        gov,
        profit_whale,
        0,
        destination_strategy,
    )

    # check our current status
    print("\nAfter harvest")
    check_status(strategy, vault)

    assert profit == 0
    share_price = vault.pricePerShare()
    assert share_price == 10 ** token.decimals()
