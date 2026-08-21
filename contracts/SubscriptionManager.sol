// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";

/**
 * @title SubscriptionManager
 * @notice SaaS subscription plans with monthly billing and premium tier verification.
 */
contract SubscriptionManager is Ownable {
    enum Tier {
        None,
        Starter,
        Growth,
        Premium,
        Enterprise
    }

    struct Plan {
        string name;
        Tier tier;
        uint256 monthlyPriceWei;
        bool active;
    }

    struct Subscription {
        Tier tier;
        uint256 planId;
        uint256 startedAt;
        uint256 expiresAt;
        bool active;
    }

    uint256 public nextPlanId = 1;
    mapping(uint256 => Plan) public plans;
    mapping(address => Subscription) public subscriptions;

    event PlanCreated(uint256 indexed planId, string name, Tier tier, uint256 monthlyPriceWei);
    event PlanStatusChanged(uint256 indexed planId, bool active);
    event Subscribed(address indexed subscriber, uint256 indexed planId, Tier tier, uint256 expiresAt);
    event SubscriptionRenewed(address indexed subscriber, uint256 indexed planId, uint256 expiresAt);
    event SubscriptionCancelled(address indexed subscriber, uint256 timestamp);

    constructor(address initialOwner) Ownable(initialOwner) {
        require(initialOwner != address(0), "SubscriptionManager: owner is zero");
        _createPlan("Starter", Tier.Starter, 0.01 ether);
        _createPlan("Growth", Tier.Growth, 0.05 ether);
        _createPlan("Premium", Tier.Premium, 0.1 ether);
        _createPlan("Enterprise", Tier.Enterprise, 0.25 ether);
    }

    function createPlan(string calldata name, Tier tier, uint256 monthlyPriceWei)
        external
        onlyOwner
        returns (uint256 planId)
    {
        require(tier != Tier.None, "SubscriptionManager: invalid tier");
        return _createPlan(name, tier, monthlyPriceWei);
    }

    function setPlanActive(uint256 planId, bool active) external onlyOwner {
        require(plans[planId].tier != Tier.None, "SubscriptionManager: unknown plan");
        plans[planId].active = active;
        emit PlanStatusChanged(planId, active);
    }

    function subscribe(uint256 planId) external payable {
        Plan memory plan = plans[planId];
        require(plan.active, "SubscriptionManager: plan inactive");
        require(plan.tier != Tier.None, "SubscriptionManager: unknown plan");
        require(msg.value >= plan.monthlyPriceWei, "SubscriptionManager: underpayment");

        uint256 started = block.timestamp;
        uint256 expires = started + 30 days;
        Subscription storage sub = subscriptions[msg.sender];

        if (sub.active && sub.expiresAt > block.timestamp) {
            // Renewal extends from current expiry
            expires = sub.expiresAt + 30 days;
            sub.expiresAt = expires;
            sub.planId = planId;
            sub.tier = plan.tier;
            emit SubscriptionRenewed(msg.sender, planId, expires);
        } else {
            subscriptions[msg.sender] = Subscription({
                tier: plan.tier,
                planId: planId,
                startedAt: started,
                expiresAt: expires,
                active: true
            });
            emit Subscribed(msg.sender, planId, plan.tier, expires);
        }

        // Refund excess
        if (msg.value > plan.monthlyPriceWei) {
            uint256 refund = msg.value - plan.monthlyPriceWei;
            (bool ok, ) = payable(msg.sender).call{value: refund}("");
            require(ok, "SubscriptionManager: refund failed");
        }
    }

    function cancelSubscription() external {
        Subscription storage sub = subscriptions[msg.sender];
        require(sub.active, "SubscriptionManager: no active subscription");
        sub.active = false;
        emit SubscriptionCancelled(msg.sender, block.timestamp);
    }

    function isSubscriptionActive(address account) public view returns (bool) {
        Subscription memory sub = subscriptions[account];
        return sub.active && sub.expiresAt >= block.timestamp;
    }

    function getActiveTier(address account) external view returns (Tier) {
        if (!isSubscriptionActive(account)) {
            return Tier.None;
        }
        return subscriptions[account].tier;
    }

    function _createPlan(string memory name, Tier tier, uint256 monthlyPriceWei)
        internal
        returns (uint256 planId)
    {
        planId = nextPlanId++;
        plans[planId] = Plan({name: name, tier: tier, monthlyPriceWei: monthlyPriceWei, active: true});
        emit PlanCreated(planId, name, tier, monthlyPriceWei);
    }
}
