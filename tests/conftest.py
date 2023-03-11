import pytest
from brownie import config, Contract, ZERO_ADDRESS, chain
from eth_abi import encode_single
import requests


@pytest.fixture(scope="function", autouse=True)
def isolate(fn_isolation):
    pass


# set this for if we want to use tenderly or not; mostly helpful because with brownie.reverts fails in tenderly forks.
use_tenderly = False


################################################## TENDERLY DEBUGGING ##################################################

# change autouse to True if we want to use this fork to help debug tests
@pytest.fixture(scope="session", autouse=use_tenderly)
def tenderly_fork(web3, chain):
    fork_base_url = "https://simulate.yearn.network/fork"
    payload = {"network_id": str(chain.id)}
    resp = requests.post(fork_base_url, headers={}, json=payload)
    fork_id = resp.json()["simulation_fork"]["id"]
    fork_rpc_url = f"https://rpc.tenderly.co/fork/{fork_id}"
    print(fork_rpc_url)
    tenderly_provider = web3.HTTPProvider(fork_rpc_url, {"timeout": 600})
    web3.provider = tenderly_provider
    print(f"https://dashboard.tenderly.co/yearn/yearn-web/fork/{fork_id}")


################################################ UPDATE THINGS BELOW HERE ################################################


@pytest.fixture(scope="session")
def gov(accounts):
    yield accounts.at("0xFEB4acf3df3cDEA7399794D0869ef76A6EfAff52", force=True)


@pytest.fixture(scope="session")
def user(accounts):
    yield accounts[0]


@pytest.fixture(scope="session")
def rewards(accounts):
    yield accounts[1]


@pytest.fixture(scope="session")
def guardian(accounts):
    yield accounts[2]


@pytest.fixture(scope="session")
def management(accounts):
    yield accounts[3]


@pytest.fixture(scope="session")
def strategist(accounts):
    yield accounts[4]


@pytest.fixture(scope="session")
def keeper(accounts):
    yield accounts[5]


@pytest.fixture(scope="session")
def token():
    token_address = "0xC25a3A3b969415c80451098fa907EC722572917F"  # this should be the address of the ERC-20 used by the strategy/vault (curve sUSD)
    yield Contract(token_address)


@pytest.fixture(scope="session")
def whale(accounts):
    yield accounts.at("0x6190e652462ee63420E45c9c554C22A3C9a694ec", True)  # 140k tokens


@pytest.fixture(scope="session")
def amount(accounts, token, user, whale):
    amount = 50000 * 10 ** token.decimals()
    # In order to get some funds for the token you are about to use,
    # it impersonate an exchange address to use it's funds.
    reserve = accounts.at(whale, force=True)
    token.transfer(user, amount, {"from": reserve})
    yield amount


@pytest.fixture(scope="session")
def profit_whale(accounts):
    yield accounts.at("0x5BB622ba7b2F09BF23F1a9b509cd210A818c53d7", True)  # 114k tokens


@pytest.fixture(scope="session")
def profit_amount(token):
    profit_amount = 500 * 10 ** token.decimals()
    yield profit_amount


# use this to test our strategy in case there are no profits
@pytest.fixture(scope="session")
def no_profit():
    no_profit = False
    yield no_profit


# use this when we might lose a few wei on conversions between want and another deposit token
# generally this will always be true if no_profit is true, even for curve/convex since we can lose a wei converting
@pytest.fixture(scope="session")
def is_slippery(no_profit):
    is_slippery = False
    if no_profit:
        is_slippery = True
    yield is_slippery


# use this to set the standard amount of time we sleep between harvests.
# generally 1 day, but can be less if dealing with smaller windows (oracles) or longer if we need to trigger weekly earnings.
@pytest.fixture(scope="session")
def sleep_time():
    hour = 3600

    # change this one right here
    hours_to_sleep = 24

    sleep_time = hour * hours_to_sleep
    yield sleep_time


@pytest.fixture(scope="session")
def health_check():
    yield Contract("0xddcea799ff1699e98edf118e0629a974df7df012")


@pytest.fixture
def vault(pm, gov, rewards, guardian, management, token):
    Vault = pm(config["dependencies"][0]).Vault
    vault = guardian.deploy(Vault)
    vault.initialize(token, gov, rewards, "", "", guardian, management)
    vault.setDepositLimit(2**256 - 1, {"from": gov})
    vault.setManagement(management, {"from": gov})
    # yield vault
    yield Contract("0x5a770DbD3Ee6bAF2802D29a901Ef11501C44797A")


@pytest.fixture
def strategy(
    strategist,
    keeper,
    origin_vault,
    destination_vault,
    RouterStrategy,
    gov,
    health_check,
):
    strategy = strategist.deploy(
        RouterStrategy, origin_vault, destination_vault, "Route yvCurve-sUSD 045"
    )
    strategy.setKeeper(keeper)

    for i in range(0, 20):
        strat_address = origin_vault.withdrawalQueue(i)
        if ZERO_ADDRESS == strat_address:
            break

        if origin_vault.strategies(strat_address)["debtRatio"] > 0:
            origin_vault.updateStrategyDebtRatio(strat_address, 0, {"from": gov})
            Contract(strat_address).harvest({"from": gov})

    strategy.setHealthCheck(health_check, {"from": origin_vault.governance()})
    origin_vault.addStrategy(strategy, 10_000, 0, 2**256 - 1, 0, {"from": gov})

    yield strategy


@pytest.fixture(scope="session")
def RELATIVE_APPROX():
    yield 1e-5


# unique fixtures for this repo


@pytest.fixture(scope="session")
def curve_susd_035():
    yield Contract("0x5a770DbD3Ee6bAF2802D29a901Ef11501C44797A")


@pytest.fixture(scope="session")
def curve_susd_045():
    yield Contract("0x5b2384D566D2E4a0b29B8eccB642C63199cd393c")


@pytest.fixture(scope="session")
def origin_vault():
    # origin vault of the route
    yield Contract("0x5a770DbD3Ee6bAF2802D29a901Ef11501C44797A")


@pytest.fixture(scope="session")
def destination_vault():
    # destination vault of the route
    yield Contract("0x5b2384D566D2E4a0b29B8eccB642C63199cd393c")


@pytest.fixture(scope="session")
def destination_strategy():
    # destination strategy of the route
    yield Contract("0x83D0458e627cFD7C6d0da12a1223bd168e1c8B64")


@pytest.fixture
def unique_strategy(
    strategist,
    keeper,
    curve_susd_035,
    curve_susd_045,
    RouterStrategy,
    gov,
    health_check,
):
    strategy = strategist.deploy(
        RouterStrategy, curve_susd_035, curve_susd_045, "Route yvCurve-sUSD 045"
    )
    strategy.setKeeper(keeper)
    strategy.setHealthCheck(health_check, {"from": curve_susd_035.governance()})

    for i in range(0, 20):
        strat_address = curve_susd_035.withdrawalQueue(i)
        if ZERO_ADDRESS == strat_address:
            break

        if curve_susd_035.strategies(strat_address)["debtRatio"] > 0:
            curve_susd_035.updateStrategyDebtRatio(strat_address, 0, {"from": gov})
            Contract(strat_address).harvest({"from": gov})

    curve_susd_035.setPerformanceFee(0, {"from": gov})
    curve_susd_035.setManagementFee(0, {"from": gov})
    curve_susd_035.addStrategy(strategy, 10_000, 0, 2**256 - 1, 0, {"from": gov})
    curve_susd_035.setDepositLimit(0, {"from": gov})

    yield strategy


@pytest.fixture
def strategy_harvest(
    vault,
    strategy,
    gov,
    token,
    whale,
    profit_whale,
    profit_amount,
    destination_vault,
    destination_strategy,
):
    def strategy_sub_harvest():
        # sleep and mine before a harvest
        chain.sleep(1)
        chain.mine(1)

        # if this is our first harvest, can keep it simple
        if strategy.estimatedTotalAssets() == 0:
            tx = strategy.harvest({"from": gov})
            chain.sleep(1)
            chain.mine(1)
            # make sure we have funds and they're all invested
            assert strategy.estimatedTotalAssets() > 0
            assert strategy.balanceOfWant() == 0

            ################## ROUTER-SPECIFIC SECTION BELOW ##################

            # extra check for router
            assert strategy.valueOfInvestment() > 0

            ################## ROUTER-SPECIFIC SECTION ABOVE ##################

        else:
            # make sure we have funds and they're all invested
            assert strategy.estimatedTotalAssets() > 0
            assert strategy.balanceOfWant() == 0

            ################## ROUTER-SPECIFIC SECTION BELOW ##################

            # extra checks for router
            assert strategy.valueOfInvestment() > 0
            prev_value = strategy.valueOfInvestment()

            # have to harvest strategy to queue that profit in 0.4.6, donations to vault don't work
            # donate some profit to our destination strategy, we will do something similar in yswaps strategies
            token.transfer(destination_strategy, profit_amount, {"from": profit_whale})
            dest_pps = destination_vault.pricePerShare()
            print("Destination PPS:", dest_pps / 1e18)

            # harvest the destination strategy, turn off health check
            destination_strategy.setDoHealthCheck(False, {"from": gov})
            tx = destination_strategy.harvest({"from": gov})

            # simulate five days of waiting for share price to bump back up
            chain.sleep(86400 * 5)
            chain.mine(1)

            dest_pps = destination_vault.pricePerShare()
            print("Destination PPS:", dest_pps / 1e18)
            print("Destination Vault Harvest Profit:", tx.events["Harvested"]["profit"] / (10 ** token.decimals()))

            # make sure we've profited
            assert strategy.valueOfInvestment() > prev_value

            ################## ROUTER-SPECIFIC SECTION ABOVE ##################

            # harvest our strategy to take a profit
            tx = strategy.harvest({"from": gov})
            print("Origin Vault Harvest Profit:", tx.events["Harvested"]["profit"] / (10 ** token.decimals()))

            # make sure we had profits and no loss
            total_gain = vault.strategies(strategy).dict()["totalGain"]
            assert total_gain > 0
            assert vault.strategies(strategy).dict()["totalLoss"] == 0

        # print out our harvested event
        harvested = tx.events["Harvested"]
        print("Harvested:", harvested)

        # sleep and mine at the end
        chain.sleep(1)
        chain.mine(1)
        print("Harvest successful")
        return tx

    yield strategy_sub_harvest
