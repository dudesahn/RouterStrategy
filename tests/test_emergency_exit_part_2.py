import pytest
import brownie
from brownie import Contract, chain, interface
from utils import harvest_strategy, check_status


# test emergency exit, after somehow losing all of our assets but miraculously getting them recovered 🍀
def test_emergency_exit_with_no_loss(
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
    target,
    use_yswaps,
    RELATIVE_APPROX,
    is_gmx,
    use_v3,
    destination_vault,
    is_migration,
):
    ## deposit to the vault after approving
    starting_whale = token.balanceOf(whale)
    token.approve(vault, 2**256 - 1, {"from": whale})
    vault.deposit(amount, {"from": whale})
    (profit, loss, extra) = harvest_strategy(
        use_v3,
        strategy,
        token,
        gov,
        profit_whale,
        profit_amount,
        target,
        destination_vault,
    )

    # check our current status
    print("\nAfter first harvest")
    strategy_params = check_status(strategy, vault)

    # evaluate our current total assets
    old_assets = vault.totalAssets()
    initial_debt = strategy_params["totalDebt"]
    starting_share_price = vault.pricePerShare()
    initial_strategy_assets = strategy.estimatedTotalAssets()
    loose_want = token.balanceOf(vault)
    # in the V2 dai vault we have some extra debt not assigned to our main strategy
    other_debt = vault.totalDebt() - strategy_params["totalDebt"]

    ################# SEND ALL FUNDS AWAY. ADJUST AS NEEDED PER STRATEGY. #################
    to_send = destination_vault.balanceOf(strategy)
    destination_vault.transfer(gov, to_send, {"from": strategy})
    assert strategy.estimatedTotalAssets() == 0

    ################# SET FALSE IF PROFIT EXPECTED. ADJUST AS NEEDED. #################
    # set this true if no profit on this test. it is normal for a strategy to not generate profit here.
    # realistically only wrapped tokens or every-block earners will see profits (convex, etc).
    # also checked in test_change_debt
    no_profit = False

    # check our current status
    print("\nAfter sending funds away")
    strategy_params = check_status(strategy, vault)

    # confirm we emptied the strategy
    assert strategy.estimatedTotalAssets() == 0

    # confirm everything else stayed the same
    assert strategy_params["debtRatio"] == 10_000
    assert strategy_params["totalLoss"] == 0
    if is_migration:
        assert (
            strategy_params["totalDebt"]
            == initial_debt
            == old_assets - loose_want - other_debt
        )
        assert vault.pricePerShare() >= starting_share_price
    else:
        assert strategy_params["totalDebt"] == initial_debt == old_assets
        assert vault.pricePerShare() == starting_share_price
    assert vault.debtOutstanding(strategy) == 0

    ################# GOV SENDS IT BACK, ADJUST AS NEEDED. #################
    # gov sends it back
    destination_vault.transfer(strategy, to_send, {"from": gov})

    # check our current status
    print("\nAfter getting funds back")
    strategy_params = check_status(strategy, vault)

    # confirm we got our assets back, exactly the same
    assert strategy.estimatedTotalAssets() == initial_strategy_assets

    # confirm everything else stayed the same
    assert strategy_params["debtRatio"] == 10_000
    assert strategy_params["totalLoss"] == 0
    if is_migration:
        assert (
            strategy_params["totalDebt"]
            == initial_debt
            == old_assets - loose_want - other_debt
        )
        assert vault.pricePerShare() >= starting_share_price
    else:
        assert strategy_params["totalDebt"] == initial_debt == old_assets
        assert vault.pricePerShare() == starting_share_price
    assert vault.debtOutstanding(strategy) == 0

    # set emergency exit
    strategy.setEmergencyExit({"from": gov})

    # check our current status
    print("\nAfter exit + before second harvest")
    strategy_params = check_status(strategy, vault)

    # only DR and debtOutstanding should have changed
    if is_migration:
        assert vault.pricePerShare() >= starting_share_price
    else:
        assert vault.pricePerShare() == starting_share_price
    assert strategy_params["debtRatio"] == 0
    assert strategy_params["totalLoss"] == 0
    assert vault.creditAvailable(strategy) == 0
    assert strategy_params["debtRatio"] == 0

    # debtOutstanding uses both totalAssets and totalDebt, starting from 10_000 DR they should all be the same
    # note that during vault.report(), if DR == 0 or emergencyShutdown is true, then estimatedTotalAssets() is used instead for debtOustanding
    if is_migration:
        assert (
            strategy_params["totalDebt"]
            == initial_debt
            == old_assets - loose_want - other_debt
            == vault.debtOutstanding(strategy)
        )
    else:
        assert (
            strategy_params["totalDebt"]
            == initial_debt
            == old_assets
            == vault.debtOutstanding(strategy)
        )

    # if slippery, then assets may differ slightly from debt
    if is_slippery:
        assert (
            pytest.approx(initial_debt, rel=RELATIVE_APPROX) == initial_strategy_assets
        )
    else:
        assert initial_debt == initial_strategy_assets

    ################# CLAIM ANY REMAINING REWARDS. ADJUST AS NEEDED PER STRATEGY. #################
    # again, harvests in emergency exit don't enter prepareReturn, so we need to claim our rewards manually
    # router the target vault still yields as normal without a harvest

    # harvest to send all funds back to the vault
    (profit, loss, extra) = harvest_strategy(
        use_v3,
        strategy,
        token,
        gov,
        profit_whale,
        profit_amount,
        target,
        destination_vault,
    )

    # check our current status
    print("\nAfter second harvest")
    strategy_params = check_status(strategy, vault)

    # DR goes to zero, loss, gain, and debt should be zero.
    assert strategy_params["debtRatio"] == 0
    assert strategy_params["totalDebt"] == strategy_params["totalLoss"] == 0

    # yswaps needs another harvest to get the final bit of profit to the vault
    if use_yswaps or is_gmx:
        old_gain = strategy_params["totalGain"]
        (profit, loss, extra) = harvest_strategy(
            use_yswaps,
            strategy,
            token,
            gov,
            profit_whale,
            profit_amount,
            target,
        )
        print("Profit:", profit)

        # check our current status
        print("\nAfter yswaps extra harvest")
        strategy_params = check_status(strategy, vault)

        # make sure we recorded our gain properly
        if not no_profit:
            assert strategy_params["totalGain"] > old_gain

    # confirm that the strategy has no funds
    assert strategy.estimatedTotalAssets() == 0

    # debtOutstanding and credit should now be zero, but we will still send any earned profits immediately back to vault
    assert vault.debtOutstanding(strategy) == vault.creditAvailable(strategy) == 0

    # many strategies will still earn some small amount of profit, or even normal profit if we hold our assets as a wrapped yield-bearing token
    if no_profit:
        assert strategy_params["totalGain"] == 0
        assert vault.pricePerShare() == starting_share_price
        assert vault.totalAssets() == old_assets
    else:
        assert strategy_params["totalGain"] > 0
        assert vault.pricePerShare() > starting_share_price
        assert vault.totalAssets() > old_assets

    # confirm we didn't lose anything, or at worst just dust
    if is_slippery and no_profit:
        assert pytest.approx(loss, rel=RELATIVE_APPROX) == 0
    else:
        assert loss == 0

    # simulate 5 days of waiting for share price to bump back up
    chain.sleep(86400 * 5)
    chain.mine(1)

    # check our current status
    print("\nAfter sleep for share price")
    strategy_params = check_status(strategy, vault)

    # share price should have gone up, without loss except for special cases
    if no_profit:
        assert (
            pytest.approx(vault.pricePerShare(), rel=RELATIVE_APPROX)
            == starting_share_price
        )
    else:
        assert vault.pricePerShare() > starting_share_price
        assert strategy_params["totalLoss"] == 0

    # withdraw and confirm we made money, or at least that we have about the same
    vault.withdraw({"from": whale})
    if no_profit:
        assert (
            pytest.approx(token.balanceOf(whale), rel=RELATIVE_APPROX) == starting_whale
        )
    else:
        assert token.balanceOf(whale) > starting_whale


# test calling emergency shutdown from the vault, harvesting to ensure we can get all assets out
def test_emergency_shutdown_from_vault(
    gov,
    token,
    vault,
    whale,
    strategy,
    chain,
    amount,
    sleep_time,
    is_slippery,
    no_profit,
    profit_whale,
    profit_amount,
    target,
    use_yswaps,
    RELATIVE_APPROX,
    is_gmx,
    use_v3,
    destination_vault,
    is_migration,
):
    ## deposit to the vault after approving
    starting_whale = token.balanceOf(whale)
    token.approve(vault, 2**256 - 1, {"from": whale})
    vault.deposit(amount, {"from": whale})
    (profit, loss, extra) = harvest_strategy(
        use_v3,
        strategy,
        token,
        gov,
        profit_whale,
        profit_amount,
        target,
        destination_vault,
    )

    # check our current status
    print("\nAfter first harvest")
    strategy_params = check_status(strategy, vault)

    # evaluate our current total assets
    old_assets = vault.totalAssets()
    initial_debt = strategy_params["totalDebt"]
    starting_share_price = vault.pricePerShare()
    initial_strategy_assets = strategy.estimatedTotalAssets()

    # simulate earnings
    chain.sleep(sleep_time)
    (profit, loss, extra) = harvest_strategy(
        use_v3,
        strategy,
        token,
        gov,
        profit_whale,
        profit_amount,
        target,
        destination_vault,
    )

    # simulate earnings
    chain.sleep(sleep_time)

    # check our current status
    print("\nAfter second harvest, before emergency shutdown")
    strategy_params = check_status(strategy, vault)

    # yswaps will not have taken this first batch of profit yet. this profit is also credit available.
    if use_yswaps or is_gmx:
        assert strategy_params["totalGain"] == 0
        assert vault.creditAvailable(strategy) == 0
    else:
        assert strategy_params["totalGain"] > 0
        assert vault.creditAvailable(strategy) > 0

    # set emergency shutdown, then confirm that the strategy has no funds
    # in emergency shutdown deposits are closed, strategies can't be added, all debt
    #  is outstanding, credit is zero, and asset for all strategy assets during report
    vault.setEmergencyShutdown(True, {"from": gov})

    # check our current status
    print("\nAfter shutdown + before third harvest")
    strategy_params = check_status(strategy, vault)

    # debtOutstanding should be the entire debt. this will also equal our initial debt as our first profit is still in the vault
    # credit available should be zero, but DR is unaffected
    if is_migration:
        # initial debt won't be the same here since we've already sent some profits back to the strategy
        assert vault.debtOutstanding(strategy) == strategy_params["totalDebt"]
    else:
        assert (
            vault.debtOutstanding(strategy)
            == strategy_params["totalDebt"]
            == initial_debt
        )
    assert vault.creditAvailable(strategy) == 0
    assert strategy_params["debtRatio"] == 10_000

    (profit, loss, extra) = harvest_strategy(
        use_v3,
        strategy,
        token,
        gov,
        profit_whale,
        profit_amount,
        target,
        destination_vault,
    )

    # check our current status
    print("\nAfter third harvest")
    strategy_params = check_status(strategy, vault)

    # yswaps should have finally taken our first round of profit
    assert strategy_params["totalGain"] > 0

    # debtOutstanding, debt, credit should now be zero, but we will still send any earned profits immediately back to vault
    assert (
        vault.debtOutstanding(strategy)
        == strategy_params["totalDebt"]
        == vault.creditAvailable(strategy)
        == 0
    )

    # harvest again to get the last of our profit with ySwaps
    if use_yswaps or is_gmx:
        old_gain = strategy_params["totalGain"]
        (profit, loss, extra) = harvest_strategy(
            use_yswaps,
            strategy,
            token,
            gov,
            profit_whale,
            profit_amount,
            target,
        )

        # check our current status
        print("\nAfter yswaps extra harvest")
        strategy_params = check_status(strategy, vault)

        # make sure we recorded our gain properly
        if not no_profit:
            assert strategy_params["totalGain"] > old_gain

    # shouldn't have any assets, unless we have slippage, then this might leave dust
    # for complete emptying, use emergencyExit
    # if it's a gmx strategy, because want/profits are auto-staked, we will trend toward zero but keep having profits
    if is_slippery:
        assert pytest.approx(strategy.estimatedTotalAssets(), rel=RELATIVE_APPROX) == 0
    elif is_gmx:
        assert strategy.estimatedTotalAssets() == extra
    else:
        assert strategy.estimatedTotalAssets() == 0

    # confirm we didn't lose anything, or at worst just dust
    if is_slippery and no_profit:
        assert pytest.approx(loss, rel=RELATIVE_APPROX) == 0
    else:
        assert loss == 0

    # simulate 5 days of waiting for share price to bump back up
    chain.sleep(86400 * 5)
    chain.mine(1)

    # check our current status
    print("\nAfter sleep for share price")
    strategy_params = check_status(strategy, vault)

    # share price should have gone up, without loss except for special cases
    if no_profit:
        assert (
            pytest.approx(vault.pricePerShare(), rel=RELATIVE_APPROX)
            == starting_share_price
        )
    else:
        assert vault.pricePerShare() > starting_share_price
        assert strategy_params["totalLoss"] == 0

    # withdraw and confirm we made money, or at least that we have about the same (profit whale has to be different from normal whale)
    vault.withdraw({"from": whale})
    if no_profit:
        assert (
            pytest.approx(token.balanceOf(whale), rel=RELATIVE_APPROX) == starting_whale
        )
    else:
        assert token.balanceOf(whale) > starting_whale
