// SPDX-License-Identifier: AGPL-3.0

pragma solidity ^0.8.15;
pragma experimental ABIEncoderV2;

import "@yearnvaults/contracts/BaseStrategy.sol";
import "@openzeppelin/contracts/utils/math/Math.sol";

interface IVault is IERC20 {
    function token() external view returns (address);

    function decimals() external view returns (uint256);

    function deposit() external;

    function pricePerShare() external view returns (uint256);

    function totalAssets() external view returns (uint256);

    function lockedProfit() external view returns (uint256);

    function lockedProfitDegradation() external view returns (uint256);

    function lastReport() external view returns (uint256);

    function withdraw(
        uint256 amount,
        address account,
        uint256 maxLoss
    ) external returns (uint256);
}

interface IOracle {
    // pull our asset price, in usdc, via yearn's oracle
    function getPriceUsdcRecommended(address tokenAddress)
        external
        view
        returns (uint256);
}

interface IHelper {
    function sharesToAmount(address vault, uint256 shares)
        external
        view
        returns (uint256);

    function amountToShares(address vault, uint256 amount)
        external
        view
        returns (uint256);
}

contract RouterStrategy is BaseStrategy {
    using SafeERC20 for IERC20;

    /* ========== STATE VARIABLES ========== */

    /// @notice The newer yVault we are routing this strategy to.
    IVault public yVault;

    /// @notice Max percentage loss we will take, in basis points (100% = 10_000). Default setting is zero.
    uint256 public maxLoss;

    /// @notice Address of our share value helper contract, which we use for conversions between shares and underlying amounts. Big 🧠 math here.
    IHelper public constant shareValueHelper =
        IHelper(0x444443bae5bB8640677A8cdF94CB8879Fec948Ec);

    /// @notice Minimum profit size in USDC that we want to harvest.
    /// @dev Only used in harvestTrigger.
    uint256 public harvestProfitMinInUsdc;

    /// @notice Maximum profit size in USDC that we want to harvest (ignore gas price once we get here).
    /// @dev Only used in harvestTrigger.
    uint256 public harvestProfitMaxInUsdc;

    /// @notice Will only be true on the original deployed contract and not on clones; we don't want to clone a clone.
    bool public isOriginal = true;

    // Do I really need to explain this one?
    string internal strategyName;

    /* ========== CONSTRUCTOR ========== */

    constructor(
        address _vault,
        address _yVault,
        string memory _strategyName
    ) BaseStrategy(_vault) {
        _initializeThis(_yVault, _strategyName);
    }

    /* ========== CLONING ========== */

    event Cloned(address indexed clone);

    function cloneRouter(
        address _vault,
        address _strategist,
        address _rewards,
        address _keeper,
        address _yVault,
        string memory _strategyName
    ) external virtual returns (address newStrategy) {
        require(isOriginal);
        // Copied from https://github.com/optionality/clone-factory/blob/master/contracts/CloneFactory.sol
        bytes20 addressBytes = bytes20(address(this));
        assembly {
            // EIP-1167 bytecode
            let clone_code := mload(0x40)
            mstore(
                clone_code,
                0x3d602d80600a3d3981f3363d3d373d3d3d363d73000000000000000000000000
            )
            mstore(add(clone_code, 0x14), addressBytes)
            mstore(
                add(clone_code, 0x28),
                0x5af43d82803e903d91602b57fd5bf30000000000000000000000000000000000
            )
            newStrategy := create(0, clone_code, 0x37)
        }

        RouterStrategy(newStrategy).initialize(
            _vault,
            _strategist,
            _rewards,
            _keeper,
            _yVault,
            _strategyName
        );

        emit Cloned(newStrategy);
    }

    function initialize(
        address _vault,
        address _strategist,
        address _rewards,
        address _keeper,
        address _yVault,
        string memory _strategyName
    ) public {
        _initialize(_vault, _strategist, _rewards, _keeper);
        require(address(yVault) == address(0));
        _initializeThis(_yVault, _strategyName);
    }

    function _initializeThis(address _yVault, string memory _strategyName)
        internal
    {
        yVault = IVault(_yVault);
        strategyName = _strategyName;
    }

    /* ========== VIEWS ========== */

    /// @notice Strategy name.
    function name() external view override returns (string memory) {
        return strategyName;
    }

    /// @notice Total assets the strategy holds, sum of loose and staked want.
    function estimatedTotalAssets()
        public
        view
        virtual
        override
        returns (uint256)
    {
        return balanceOfWant() + valueOfInvestment();
    }

    /// @notice Assets delegated to another vault. Helps to avoid double-counting of TVL.
    function delegatedAssets() public view override returns (uint256) {
        return vault.strategies(address(this)).totalDebt;
    }

    /// @notice Balance of want sitting in our strategy.
    function balanceOfWant() public view returns (uint256) {
        return want.balanceOf(address(this));
    }

    /// @notice Balance of underlying we are holding as vault tokens of our delegated vault.
    function valueOfInvestment() public view virtual returns (uint256) {
        return
            shareValueHelper.sharesToAmount(
                address(yVault),
                yVault.balanceOf(address(this))
            );
    }

    /// @notice Balance of underlying we will gain on our next harvest
    function claimableProfits() public view returns (uint256) {
        return valueOfInvestment() - (delegatedAssets() - balanceOfWant());
    }

    /* ========== CORE STRATEGY FUNCTIONS ========== */

    function prepareReturn(uint256 _debtOutstanding)
        internal
        virtual
        override
        returns (
            uint256 _profit,
            uint256 _loss,
            uint256 _debtPayment
        )
    {
        uint256 _totalDebt = vault.strategies(address(this)).totalDebt;
        uint256 _totalAsset = estimatedTotalAssets();

        // Estimate the profit we have so far
        if (_totalDebt <= _totalAsset) {
            unchecked {
                _profit = _totalAsset - _totalDebt;
            }
        }

        // We take profit and debt
        uint256 _amountFreed;
        (_amountFreed, _loss) = liquidatePosition(_debtOutstanding + _profit);
        _debtPayment = Math.min(_debtOutstanding, _amountFreed);

        if (_loss > _profit) {
            // Example:
            // debtOutstanding 100, profit 40, _amountFreed 100, _loss 50
            // loss should be 10, (50-40)
            // profit should endup in 0
            unchecked {
                _loss = _loss - _profit;
            }
            _profit = 0;
        } else {
            // Example:
            // debtOutstanding 100, profit 50, _amountFreed 140, _loss 10
            // _profit should be 40, (50 profit - 10 loss)
            // loss should end up in be 0
            unchecked {
                _profit = _profit - _loss;
            }
            _loss = 0;
        }
    }

    function adjustPosition(uint256 _debtOutstanding)
        internal
        virtual
        override
    {
        if (emergencyExit) {
            return;
        }

        uint256 balance = balanceOfWant();
        if (balance > 0) {
            _checkAllowance(address(yVault), address(want), balance);
            yVault.deposit();
        }
    }

    function liquidatePosition(uint256 _amountNeeded)
        internal
        virtual
        override
        returns (uint256 _liquidatedAmount, uint256 _loss)
    {
        uint256 balance = balanceOfWant();
        if (balance >= _amountNeeded) {
            return (_amountNeeded, 0);
        }

        uint256 toWithdraw;
        unchecked {
            toWithdraw = _amountNeeded - balance;
        }
        _withdrawFromYVault(toWithdraw);

        uint256 looseWant = balanceOfWant();
        if (_amountNeeded > looseWant) {
            _liquidatedAmount = looseWant;
            unchecked {
                _loss = _amountNeeded - looseWant;
            }
        } else {
            _liquidatedAmount = _amountNeeded;
        }
    }

    function withdrawFromYVault(uint256 _amount) external onlyVaultManagers {
        _withdrawFromYVault(_amount);
    }

    function _withdrawFromYVault(uint256 _amount) internal {
        if (_amount == 0) {
            return;
        }

        uint256 _balanceOfYShares = yVault.balanceOf(address(this));
        uint256 sharesToWithdraw =
            Math.min(
                shareValueHelper.amountToShares(address(yVault), _amount),
                _balanceOfYShares
            );

        if (sharesToWithdraw == 0) {
            return;
        }

        yVault.withdraw(sharesToWithdraw, address(this), maxLoss);
    }

    function liquidateAllPositions()
        internal
        virtual
        override
        returns (uint256 _amountFreed)
    {
        return
            yVault.withdraw(
                yVault.balanceOf(address(this)),
                address(this),
                maxLoss
            );
    }

    function prepareMigration(address _newStrategy) internal virtual override {
        IERC20(yVault).safeTransfer(
            _newStrategy,
            IERC20(yVault).balanceOf(address(this))
        );
    }

    function protectedTokens()
        internal
        view
        override
        returns (address[] memory ret)
    {
        ret = new address[](1);
        ret[0] = address(yVault);
    }

    /// @notice Convert our keeper's eth cost into want
    /// @dev We don't use this since we don't factor call cost into our harvestTrigger.
    /// @param _amtInWei Amount of ether spent.
    /// @return Value of ether in want.
    function ethToWant(uint256 _amtInWei)
        public
        view
        virtual
        override
        returns (uint256)
    {
        return _amtInWei;
    }

    /* ========== KEEP3RS ========== */

    /**
     * @notice
     *  Provide a signal to the keeper that harvest() should be called.
     *
     *  Don't harvest if a strategy is inactive, or if it needs an earmark first.
     *  If our profit exceeds our upper limit, then harvest no matter what. For
     *  our lower profit limit, credit threshold, max delay, and manual force trigger,
     *  only harvest if our gas price is acceptable.
     *
     * @param callCostinEth The keeper's estimated gas cost to call harvest() (in wei).
     * @return True if harvest() should be called, false otherwise.
     */
    function harvestTrigger(uint256 callCostinEth)
        public
        view
        override
        returns (bool)
    {
        // Should not trigger if strategy is not active (no assets and no debtRatio). This means we don't need to adjust keeper job.
        if (!isActive()) {
            return false;
        }

        // harvest if we have a profit to claim at our upper limit without considering gas price
        uint256 claimableProfit = claimableProfitInUsdc();
        if (claimableProfit > harvestProfitMaxInUsdc) {
            return true;
        }

        // check if the base fee gas price is higher than we allow. if it is, block harvests.
        if (!isBaseFeeAcceptable()) {
            return false;
        }

        // trigger if we want to manually harvest, but only if our gas price is acceptable
        if (forceHarvestTriggerOnce) {
            return true;
        }

        // harvest if we have a sufficient profit to claim, but only if our gas price is acceptable
        if (claimableProfit > harvestProfitMinInUsdc) {
            return true;
        }

        StrategyParams memory params = vault.strategies(address(this));
        // harvest regardless of profit once we reach our maxDelay
        if (block.timestamp - params.lastReport > maxReportDelay) {
            return true;
        }

        // harvest our credit if it's above our threshold
        if (vault.creditAvailable() > creditThreshold) {
            return true;
        }

        // otherwise, we don't harvest
        return false;
    }

    /// @notice Calculates the profit if all claimable assets were sold for USDC (6 decimals).
    /// @dev Uses yearn's lens oracle, if returned values are strange then troubleshoot there.
    /// @return Total return in USDC from taking profits on yToken gains.
    function claimableProfitInUsdc() public view returns (uint256) {
        IOracle yearnOracle =
            IOracle(0x83d95e0D5f402511dB06817Aff3f9eA88224B030); // yearn lens oracle
        uint256 underlyingPrice =
            yearnOracle.getPriceUsdcRecommended(address(want));

        // Oracle returns prices as 6 decimals, so multiply by claimable amount and divide by token decimals
        return (claimableProfits() * underlyingPrice) / (10**yVault.decimals());
    }

    /// @notice Set the maximum loss we will accept (due to slippage or locked funds) on a vault withdrawal.
    /// @dev Generally, this should be zero, and this function will only be used in special/emergency cases.
    /// @param _maxLoss Max percentage loss we will take, in basis points (100% = 10_000).
    function setMaxLoss(uint256 _maxLoss) public onlyVaultManagers {
        maxLoss = _maxLoss;
    }

    function _checkAllowance(
        address _contract,
        address _token,
        uint256 _amount
    ) internal {
        if (IERC20(_token).allowance(address(this), _contract) < _amount) {
            IERC20(_token).safeApprove(_contract, 0);
            IERC20(_token).safeApprove(_contract, type(uint256).max);
        }
    }
}
