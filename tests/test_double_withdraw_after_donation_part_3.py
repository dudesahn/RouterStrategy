from brownie import chain, ZERO_ADDRESS
import pytest
from utils import harvest_strategy, check_status

# these tests are identical to our withdraw_after_donation, except we also add in a withdrawal from the target vault at the same time


# lower debtRatio to 0, donate, withdraw more than the donation, then harvest
# this is the same as test 3 but with some extra checks that the strategy is empty
def test_withdraw_after_donation_7(
    gov,
    token,
    vault,
    strategist,
    whale,
    strategy,
    amount,
    sleep_time,
    is_slippery,
    no_profit,
    profit_whale,
    profit_amount,
    target,
    vault_address,
    is_gmx,
    use_v3,
    destination_vault,
    is_migration,
    use_yswaps,
    RELATIVE_APPROX,
    use_old,
):

    ## deposit to the vault after approving
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
    print("\nAfter first harvest, before DR reduction")
    strategy_params = check_status(strategy, vault)
    prev_params = strategy_params

    # evaluate our current total assets
    old_assets = vault.totalAssets()
    initial_debt = strategy_params["totalDebt"]
    starting_share_price = vault.pricePerShare()
    initial_strategy_assets = strategy.estimatedTotalAssets()
    prev_assets = vault.totalAssets()

    # reduce our debtRatio to 0%
    starting_debt_ratio = prev_params["debtRatio"]
    vault.updateStrategyDebtRatio(strategy, 0, {"from": gov})
    assert vault.strategies(strategy)["debtRatio"] == 0

    # check our current status
    print("\nAfter reducing DR, before donation")
    strategy_params = check_status(strategy, vault)

    # debtOutstanding should be same as our initial_debt. nothing else has changed yet
    assert vault.debtOutstanding(strategy) == initial_debt
    assert strategy_params["totalDebt"] == initial_debt
    assert vault.creditAvailable(strategy) == 0

    # our whale donates to the vault, what a nice person! 🐳
    donation = amount / 2
    token.transfer(strategy, donation, {"from": whale})

    # check our current status
    print("\nAfter token donation, before withdrawal")
    strategy_params = check_status(strategy, vault)

    # we should have more assets but the same debt
    assert strategy.estimatedTotalAssets() > initial_strategy_assets
    assert strategy_params["totalDebt"] == initial_debt

    # have our whale withdraw more than the donation, ensuring we pull from strategy
    to_withdraw = donation * 1.05
    if vault_address == ZERO_ADDRESS:
        vault.withdraw(to_withdraw, {"from": whale})
    else:
        # convert since our PPS isn't 1 (live vault!)
        withdrawal_in_shares = to_withdraw * 1e18 / vault.pricePerShare()
        vault.withdraw(withdrawal_in_shares, {"from": whale})

    # withdraw some funds from our target vault, shouldn't affect anything
    if not use_old and not use_v3:
        strategy.withdrawFromYVault(donation / 10, {"from": gov})

    # simulate some earnings
    chain.sleep(sleep_time)

    # check our current status
    print("\nAfter withdrawal, before harvest")
    strategy_params = check_status(strategy, vault)

    # make sure things are going as we expect
    if is_migration:
        assert strategy_params["totalGain"] == profit
    else:
        assert strategy_params["totalGain"] == 0
    assert strategy_params["debtRatio"] == 0
    if is_slippery:
        assert pytest.approx(strategy_params["totalLoss"], rel=RELATIVE_APPROX) == 0
    else:
        assert strategy_params["totalLoss"] == 0
    assert vault.creditAvailable(strategy) == 0
    assert (
        pytest.approx(initial_debt, rel=RELATIVE_APPROX)
        == strategy_params["totalDebt"] + to_withdraw
    )
    assert (
        pytest.approx(vault.debtOutstanding(strategy), rel=RELATIVE_APPROX)
        == strategy_params["totalDebt"]
    )

    # after our donation, best to use health check in case our donation profit is too big
    strategy.setDoHealthCheck(False, {"from": gov})
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
    print("\nAfter harvest to reduce debt")
    strategy_params = check_status(strategy, vault)

    # make sure things are going as we expect
    if use_yswaps or no_profit or is_gmx:
        assert strategy_params["totalGain"] == donation
    else:
        assert strategy_params["totalGain"] > donation
    assert strategy_params["debtRatio"] == 0
    if is_slippery:
        assert pytest.approx(strategy_params["totalLoss"], rel=RELATIVE_APPROX) == 0
    else:
        assert strategy_params["totalLoss"] == 0
    assert strategy_params["totalDebt"] == 0
    assert vault.debtOutstanding(strategy) == 0

    # zero since we set our DR to zero
    assert vault.creditAvailable(strategy) == 0

    # harvest again so the strategy reports the profit
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

    # record our new strategy params
    new_params = vault.strategies(strategy)

    # sleep 5 days to allow share price to normalize
    chain.sleep(86400 * 5)
    chain.mine(1)

    # check our current status
    print("\nAfter sleep for share price")
    strategy_params = check_status(strategy, vault)

    # make sure things are going as we expect
    assert strategy_params["totalGain"] > donation
    assert strategy_params["debtRatio"] == 0
    if is_slippery:
        assert pytest.approx(strategy_params["totalLoss"], rel=RELATIVE_APPROX) == 0
    else:
        assert strategy_params["totalLoss"] == 0
    assert vault.debtOutstanding(strategy) == 0
    assert vault.creditAvailable(strategy) == 0

    # specifically check that our profit is greater than our donation or at least close if we get slippage on deposit/withdrawal and have no profit
    profit = new_params["totalGain"] - prev_params["totalGain"]
    if no_profit:
        assert pytest.approx(profit, rel=RELATIVE_APPROX) == donation
    else:
        assert profit > donation

    # check that we didn't add any more loss, or close if we get slippage on deposit/withdrawal
    if is_slippery:
        assert (
            pytest.approx(new_params["totalLoss"], rel=RELATIVE_APPROX)
            == prev_params["totalLoss"]
        )
    else:
        assert new_params["totalLoss"] == prev_params["totalLoss"]

    # assert that our vault total assets, multiplied by our debtRatio, is about equal to our estimated total assets plus credit available
    # we multiply this by the debtRatio of our strategy out of 10_000 total
    # a vault only knows it has assets if the strategy has reported. also, if strategy assets are zero, we don't get additional yswaps profit.
    # so in this case, no difference expected between yswaps and non-yswaps strategies. gmx will have some dust unrealized profits.
    assert pytest.approx(
        strategy.estimatedTotalAssets() + vault.creditAvailable(strategy),
        rel=RELATIVE_APPROX,
    ) == int(vault.totalAssets() * new_params["debtRatio"] / 10_000 + extra)

    # check everywhere to make sure we emptied out the strategy
    if is_slippery:
        assert strategy.estimatedTotalAssets() <= 10
        assert token.balanceOf(strategy) == 0
    elif is_gmx:
        assert strategy.estimatedTotalAssets() == extra
    else:
        assert strategy.estimatedTotalAssets() == 0
        assert token.balanceOf(strategy) == 0

    # assert that our total assets have gone up or stayed the same when accounting for the donation and withdrawal, or that we're close at least
    current_assets = vault.totalAssets()
    if no_profit:
        assert (
            pytest.approx(donation - to_withdraw + prev_assets, rel=RELATIVE_APPROX)
            == current_assets
        )
    else:
        assert current_assets > donation - to_withdraw + prev_assets

    new_params = vault.strategies(strategy)

    # assert that our strategy has no debt
    assert new_params["totalDebt"] == 0
    assert vault.debtOutstanding(strategy) == 0


# lower debtRatio to 0, donate, withdraw less than the donation, then harvest
# this is the same as test 2 but with some extra checks that the strategy is empty
def test_withdraw_after_donation_8(
    gov,
    token,
    vault,
    strategist,
    whale,
    strategy,
    amount,
    sleep_time,
    is_slippery,
    no_profit,
    profit_whale,
    profit_amount,
    target,
    vault_address,
    is_gmx,
    use_v3,
    destination_vault,
    is_migration,
    use_yswaps,
    RELATIVE_APPROX,
    use_old,
):

    ## deposit to the vault after approving
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
    print("\nAfter first harvest, before DR reduction")
    strategy_params = check_status(strategy, vault)
    prev_params = strategy_params

    # evaluate our current total assets
    old_assets = vault.totalAssets()
    initial_debt = strategy_params["totalDebt"]
    starting_share_price = vault.pricePerShare()
    initial_strategy_assets = strategy.estimatedTotalAssets()
    prev_assets = vault.totalAssets()

    # reduce our debtRatio to 0%
    starting_debt_ratio = prev_params["debtRatio"]
    vault.updateStrategyDebtRatio(strategy, 0, {"from": gov})
    assert vault.strategies(strategy)["debtRatio"] == 0

    # check our current status
    print("\nAfter reducing DR, before donation")
    strategy_params = check_status(strategy, vault)

    # debtOutstanding should be same as our initial_debt. nothing else has changed yet
    assert vault.debtOutstanding(strategy) == initial_debt
    assert strategy_params["totalDebt"] == initial_debt
    assert vault.creditAvailable(strategy) == 0

    # our whale donates to the vault, what a nice person! 🐳
    donation = amount / 2
    token.transfer(strategy, donation, {"from": whale})

    # check our current status
    print("\nAfter token donation, before withdrawal")
    strategy_params = check_status(strategy, vault)

    # we should have more assets but the same debt
    assert strategy.estimatedTotalAssets() > initial_strategy_assets
    assert strategy_params["totalDebt"] == initial_debt

    # have our whale withdraw half of the donation, this ensures that we test withdrawing without pulling from the staked balance
    to_withdraw = donation / 2
    if vault_address == ZERO_ADDRESS:
        vault.withdraw(to_withdraw, {"from": whale})
    else:
        # convert since our PPS isn't 1 (live vault!)
        withdrawal_in_shares = to_withdraw * 1e18 / vault.pricePerShare()
        vault.withdraw(withdrawal_in_shares, {"from": whale})

    # withdraw some funds from our target vault, shouldn't affect anything
    if not use_old and not use_v3:
        strategy.withdrawFromYVault(donation / 10, {"from": gov})

    # simulate some earnings
    chain.sleep(sleep_time)

    # check our current status
    print("\nAfter withdrawal, before harvest")
    strategy_params = check_status(strategy, vault)

    # make sure things are going as we expect
    if is_migration:
        assert strategy_params["totalGain"] == profit
    else:
        assert strategy_params["totalGain"] == 0
    assert strategy_params["debtRatio"] == 0
    if is_slippery:
        assert pytest.approx(strategy_params["totalLoss"], rel=RELATIVE_APPROX) == 0
    else:
        assert strategy_params["totalLoss"] == 0
    assert vault.creditAvailable(strategy) == 0
    assert (
        pytest.approx(initial_debt, rel=RELATIVE_APPROX)
        == strategy_params["totalDebt"] + to_withdraw
    )
    assert (
        pytest.approx(vault.debtOutstanding(strategy), rel=RELATIVE_APPROX)
        == strategy_params["totalDebt"]
    )

    # after our donation, best to use health check in case our donation profit is too big
    strategy.setDoHealthCheck(False, {"from": gov})
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
    print("\nAfter harvest to reduce debt")
    strategy_params = check_status(strategy, vault)

    # make sure things are going as we expect
    if use_yswaps or no_profit or is_gmx:
        assert strategy_params["totalGain"] == donation
    else:
        assert strategy_params["totalGain"] > donation
    assert strategy_params["debtRatio"] == 0
    if is_slippery:
        assert pytest.approx(strategy_params["totalLoss"], rel=RELATIVE_APPROX) == 0
    else:
        assert strategy_params["totalLoss"] == 0
    assert strategy_params["totalDebt"] == 0
    assert vault.debtOutstanding(strategy) == 0

    # zero since we set our DR to zero
    assert vault.creditAvailable(strategy) == 0

    # harvest again so the strategy reports the profit
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

    # record our new strategy params
    new_params = vault.strategies(strategy)

    # sleep 5 days to allow share price to normalize
    chain.sleep(86400 * 5)
    chain.mine(1)

    # check our current status
    print("\nAfter sleep for share price")
    strategy_params = check_status(strategy, vault)

    # make sure things are going as we expect
    assert strategy_params["totalGain"] > donation
    assert strategy_params["debtRatio"] == 0
    if is_slippery:
        assert pytest.approx(strategy_params["totalLoss"], rel=RELATIVE_APPROX) == 0
    else:
        assert strategy_params["totalLoss"] == 0
    assert vault.debtOutstanding(strategy) == 0
    assert vault.creditAvailable(strategy) == 0

    # specifically check that our profit is greater than our donation or at least close if we get slippage on deposit/withdrawal and have no profit
    profit = new_params["totalGain"] - prev_params["totalGain"]
    if no_profit:
        assert pytest.approx(profit, rel=RELATIVE_APPROX) == donation
    else:
        assert profit > donation

    # check that we didn't add any more loss, or close if we get slippage on deposit/withdrawal
    if is_slippery:
        assert (
            pytest.approx(new_params["totalLoss"], rel=RELATIVE_APPROX)
            == prev_params["totalLoss"]
        )
    else:
        assert new_params["totalLoss"] == prev_params["totalLoss"]

    # assert that our vault total assets, multiplied by our debtRatio, is about equal to our estimated total assets plus credit available
    # we multiply this by the debtRatio of our strategy out of 10_000 total
    # a vault only knows it has assets if the strategy has reported. also, if strategy assets are zero, we don't get additional yswaps profit.
    # so in this case, no difference expected between yswaps and non-yswaps strategies. gmx will have some dust unrealized profits.
    assert pytest.approx(
        strategy.estimatedTotalAssets() + vault.creditAvailable(strategy),
        rel=RELATIVE_APPROX,
    ) == int(vault.totalAssets() * new_params["debtRatio"] / 10_000 + extra)

    # check everywhere to make sure we emptied out the strategy
    if is_slippery:
        assert strategy.estimatedTotalAssets() <= 10
        assert token.balanceOf(strategy) == 0
    elif is_gmx:
        assert strategy.estimatedTotalAssets() == extra
    else:
        assert strategy.estimatedTotalAssets() == 0
        assert token.balanceOf(strategy) == 0

    # assert that our total assets have gone up or stayed the same when accounting for the donation and withdrawal, or that we're close at least
    current_assets = vault.totalAssets()
    if no_profit:
        assert (
            pytest.approx(donation - to_withdraw + prev_assets, rel=RELATIVE_APPROX)
            == current_assets
        )
    else:
        assert current_assets > donation - to_withdraw + prev_assets

    new_params = vault.strategies(strategy)

    # assert that our strategy has no debt
    assert new_params["totalDebt"] == 0
    assert vault.debtOutstanding(strategy) == 0
