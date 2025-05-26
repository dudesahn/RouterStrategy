import pytest
import brownie
from brownie import interface, chain, accounts, Contract
import time


# returns (profit, loss) of a harvest
def harvest_strategy(
    use_v3,
    strategy,
    token,
    gov,
    profit_whale,
    profit_amount,
    destination_strategy,
    destination_vault,
):

    # reset everything with a sleep and mine
    chain.sleep(1)
    chain.mine(1)

    # add in any custom logic needed here, for instance with router strategy (also reason we have a destination strategy).
    # also add in any custom logic needed to get raw reward assets to the strategy (like for liquity)

    ####### ADD LOGIC AS NEEDED FOR CLAIMING/SENDING REWARDS TO STRATEGY #######
    # usually this is automatic, but it may need to be externally triggered

    # since we don't use yswaps for the main strategy, we don't need to ever prevent profit in the destination vault
    # send profit to our destination vault's strategy
    # if we don't want to harvest our destination strategy, we pass profit_amount to zero
    extra = 0
    if profit_amount > 0:
        extra = trade_handler_action(
            destination_strategy,
            token,
            gov,
            profit_whale,
            profit_amount,
            use_v3,
            destination_vault,
        )

    # check loose want before harvest
    print("Loose want before harvest:", strategy.balanceOfWant())
    print("Vault balance of want:", token.balanceOf(strategy.vault()))

    # do hacky workaround for V3 version...anvil/brownie seems to struggle with it
    if use_v3:
        # check gain before
        vault = Contract(strategy.vault())
        before_gain = vault.strategies(strategy)["totalGain"]
        before_loss = vault.strategies(strategy)["totalLoss"]
        # we can use the tx for debugging if needed
        strategy.harvest({"from": gov})
        profit = vault.strategies(strategy)["totalGain"] - before_gain
        loss = vault.strategies(strategy)["totalLoss"] - before_loss
    else:
        # we can use the tx for debugging if needed
        tx = strategy.harvest({"from": gov})
        profit = tx.events["Harvested"]["profit"]
        loss = tx.events["Harvested"]["loss"]
        print("Debt Payment:", tx.events["Harvested"]["debtPayment"])
        print("Debt Outstanding:", tx.events["Harvested"]["debtOutstanding"])

    # assert there are no loose funds in strategy after a harvest
    print("Loose want after harvest:", strategy.balanceOfWant())
    print("Vault balance of want:", token.balanceOf(strategy.vault()))

    # I think we should only ever have 1 wei extra here
    assert strategy.balanceOfWant() <= 1

    # reset everything with a sleep and mine
    chain.sleep(1)
    chain.mine(1)

    # return our profit, loss
    return (profit, loss, extra)


# simulate the trade handler sweeping out assets and sending back profit
def trade_handler_action(
    destination_strategy,
    token,
    gov,
    profit_whale,
    profit_amount,
    use_v3,
    destination_vault,
):
    ####### ADD LOGIC AS NEEDED FOR SENDING REWARDS OUT AND PROFITS IN #######
    # in this strategy, we actually need to send profits to our destination strategy and harvest that

    # here we should send profit to the destination strategy and then harvest it
    # this is a bit different than "normal" yswaps logic since our main strategy doesn't use yswaps
    token.transfer(destination_strategy, profit_amount, {"from": profit_whale})

    # turn off health check for destination strategy
    if use_v3:
        if destination_strategy.profitMaxUnlockTime() != 0:
            destination_strategy.setProfitMaxUnlockTime(
                0, {"from": destination_strategy.management()}
            )
        destination_strategy.report({"from": destination_strategy.management()})
        if destination_vault.profitMaxUnlockTime() != 0:
            destination_vault.setProfitMaxUnlockTime(0, {"from": gov})
        target_tx = destination_vault.process_report(
            destination_strategy, {"from": gov}
        )
        target_profit = target_tx.events["StrategyReported"]["gain"]
    else:
        destination_strategy.setDoHealthCheck(False, {"from": gov})
        target_tx = destination_strategy.harvest({"from": gov})
        target_profit = target_tx.events["Harvested"]["profit"]

    # sleep 5 days so share price normalizes
    chain.sleep(86400 * 5)
    chain.mine(1)

    # make sure we made a profit
    assert target_profit > 0
    print("Profit taken in destination vault")

    # we don't use extra for anything here
    return 0


# do a check on our strategy and vault of choice
def check_status(
    strategy,
    vault,
):
    # check our current status
    strategy_params = vault.strategies(strategy)
    vault_assets = vault.totalAssets()
    debt_outstanding = vault.debtOutstanding(strategy)
    credit_available = vault.creditAvailable(strategy)
    total_debt = vault.totalDebt()
    share_price = vault.pricePerShare()
    strategy_debt = strategy_params["totalDebt"]
    strategy_loss = strategy_params["totalLoss"]
    strategy_gain = strategy_params["totalGain"]
    strategy_debt_ratio = strategy_params["debtRatio"]
    strategy_assets = strategy.estimatedTotalAssets()

    # print our stuff
    print("Vault Assets:", vault_assets)
    print("Strategy Debt Outstanding:", debt_outstanding)
    print("Strategy Credit Available:", credit_available)
    print("Vault Total Debt:", total_debt)
    print("Vault Share Price:", share_price)
    print("Strategy Total Debt:", strategy_debt)
    print("Strategy Total Loss:", strategy_loss)
    print("Strategy Total Gain:", strategy_gain)
    print("Strategy Debt Ratio:", strategy_debt_ratio)
    print("Strategy Estimated Total Assets:", strategy_assets, "\n")

    # print simplified versions if we have something more than dust
    token = interface.IERC20(vault.token())
    if vault_assets > 10:
        print(
            "Decimal-Corrected Vault Assets:", vault_assets / (10 ** token.decimals())
        )
    if debt_outstanding > 10:
        print(
            "Decimal-Corrected Strategy Debt Outstanding:",
            debt_outstanding / (10 ** token.decimals()),
        )
    if credit_available > 10:
        print(
            "Decimal-Corrected Strategy Credit Available:",
            credit_available / (10 ** token.decimals()),
        )
    if total_debt > 10:
        print(
            "Decimal-Corrected Vault Total Debt:", total_debt / (10 ** token.decimals())
        )
    if share_price > 10:
        print("Decimal-Corrected Share Price:", share_price / (10 ** token.decimals()))
    if strategy_debt > 10:
        print(
            "Decimal-Corrected Strategy Total Debt:",
            strategy_debt / (10 ** token.decimals()),
        )
    if strategy_loss > 10:
        print(
            "Decimal-Corrected Strategy Total Loss:",
            strategy_loss / (10 ** token.decimals()),
        )
    if strategy_gain > 10:
        print(
            "Decimal-Corrected Strategy Total Gain:",
            strategy_gain / (10 ** token.decimals()),
        )
    if strategy_assets > 10:
        print(
            "Decimal-Corrected Strategy Total Assets:",
            strategy_assets / (10 ** token.decimals()),
        )

    return strategy_params
