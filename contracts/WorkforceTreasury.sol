// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/**
 * @title WorkforceTreasury
 * @notice Receives platform payments, tracks accounting, and allows owner withdrawals.
 */
contract WorkforceTreasury is Ownable, ReentrancyGuard {
    uint256 public totalReceived;
    uint256 public totalWithdrawn;

    mapping(address => uint256) public contributions;

    event PaymentReceived(address indexed from, uint256 amount, string memo, uint256 timestamp);
    event Withdrawal(address indexed to, uint256 amount, uint256 timestamp);
    event AccountingSynced(uint256 balance, uint256 totalReceived, uint256 totalWithdrawn);

    constructor(address initialOwner) Ownable(initialOwner) {
        require(initialOwner != address(0), "WorkforceTreasury: owner is zero");
    }

    receive() external payable {
        _recordPayment(msg.sender, msg.value, "receive");
    }

    fallback() external payable {
        _recordPayment(msg.sender, msg.value, "fallback");
    }

    function deposit(string calldata memo) external payable {
        require(msg.value > 0, "WorkforceTreasury: zero deposit");
        _recordPayment(msg.sender, msg.value, memo);
    }

    function withdraw(address payable to, uint256 amount) external onlyOwner nonReentrant {
        require(to != address(0), "WorkforceTreasury: to is zero");
        require(amount > 0, "WorkforceTreasury: amount is zero");
        require(address(this).balance >= amount, "WorkforceTreasury: insufficient balance");

        totalWithdrawn += amount;
        (bool ok, ) = to.call{value: amount}("");
        require(ok, "WorkforceTreasury: withdraw failed");

        emit Withdrawal(to, amount, block.timestamp);
        emit AccountingSynced(address(this).balance, totalReceived, totalWithdrawn);
    }

    function treasuryBalance() external view returns (uint256) {
        return address(this).balance;
    }

    function accounting()
        external
        view
        returns (uint256 balance, uint256 received, uint256 withdrawn, uint256 net)
    {
        balance = address(this).balance;
        received = totalReceived;
        withdrawn = totalWithdrawn;
        net = received > withdrawn ? received - withdrawn : 0;
    }

    function _recordPayment(address from, uint256 amount, string memory memo) internal {
        require(amount > 0, "WorkforceTreasury: zero payment");
        totalReceived += amount;
        contributions[from] += amount;
        emit PaymentReceived(from, amount, memo, block.timestamp);
        emit AccountingSynced(address(this).balance, totalReceived, totalWithdrawn);
    }
}
