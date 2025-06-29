from brownie import (
    StrategyRouterV2,
    StrategyRouterV3,
    accounts,
    config,
    Contract,
    project,
    web3,
)
import click

def main():
    deployer = accounts.load("llc2")

    # use this to decide whether to deploy V2 or V3 router strategy and confirm we selected correctly
    deploy_v2 = click.prompt(
        "Do you want to deploy the V2 => V2 version of this strategy?", type=bool
    )
    if not deploy_v2:
        deploy_v3 = click.prompt(
            "Do you want to deploy the V2 => V3 version of this strategy?", type=bool
        )
        assert deploy_v3

    if deploy_v2:
        contract_name = StrategyRouterV2
        # 3Crypto
        vault = Contract("0xE537B5cc158EB71037D4125BDD7538421981E6AA")
        destination_vault = Contract("0x8078198Fc424986ae89Ce4a910Fc109587b6aBF3")
        strategy_name = "StrategyRouterV2-Curve-3Crypto"
    else:
        contract_name = StrategyRouterV3
        # DAI 0.4.3
        vault = Contract("0xdA816459F1AB5631232FE5e97a05BBBb94970c95")
        destination_vault = Contract("0x028eC7330ff87667b6dfb0D94b954c820195336c")
        strategy_name = "StrategyRouterV3-DAI"

    print("Strategy Vault:", vault.name(), vault.address)
    print("Destination Vault:", destination_vault.name(), destination_vault.address)

    strategy = deployer.deploy(
        contract_name,
        vault.address,
        destination_vault.address,
        strategy_name,
        publish_source=True,
    )

    # set keeper for our stealth job
    keeper = "0x736D7e3c5a6CB2CE3B764300140ABF476F6CFCCF"
    strategy.setKeeper(keeper, {"from": deployer})
    # strategy.setCreditThreshold(20_000e18)
    # vault.addStrategy(strategy, 10_000, 0, 2**256 - 1, 1_000, {"from": gov})
    # yield strategy
