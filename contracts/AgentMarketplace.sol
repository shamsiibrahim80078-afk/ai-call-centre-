// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";

/**
 * @title AgentMarketplace
 * @notice Register AI agents, publish services, and purchase agent access.
 */
contract AgentMarketplace is Ownable {
    struct AgentListing {
        address provider;
        string agentId;
        string name;
        string serviceUri;
        uint256 priceWei;
        bool published;
        uint256 totalPurchases;
    }

    uint256 public nextListingId = 1;
    mapping(uint256 => AgentListing) public listings;
    mapping(string => uint256) public listingIdByAgentId;
    mapping(address => mapping(uint256 => bool)) public hasAccess;

    event AgentRegistered(
        uint256 indexed listingId,
        address indexed provider,
        string agentId,
        string name,
        uint256 priceWei
    );
    event AgentPublished(uint256 indexed listingId, bool published);
    event AgentAccessPurchased(
        uint256 indexed listingId,
        address indexed buyer,
        address indexed provider,
        uint256 priceWei,
        uint256 timestamp
    );

    constructor(address initialOwner) Ownable(initialOwner) {
        require(initialOwner != address(0), "AgentMarketplace: owner is zero");
    }

    function registerAgent(
        string calldata agentId,
        string calldata name,
        string calldata serviceUri,
        uint256 priceWei
    ) external returns (uint256 listingId) {
        require(bytes(agentId).length > 0, "AgentMarketplace: agentId required");
        require(bytes(name).length > 0, "AgentMarketplace: name required");
        require(listingIdByAgentId[agentId] == 0, "AgentMarketplace: agent exists");

        listingId = nextListingId++;
        listings[listingId] = AgentListing({
            provider: msg.sender,
            agentId: agentId,
            name: name,
            serviceUri: serviceUri,
            priceWei: priceWei,
            published: true,
            totalPurchases: 0
        });
        listingIdByAgentId[agentId] = listingId;

        emit AgentRegistered(listingId, msg.sender, agentId, name, priceWei);
        emit AgentPublished(listingId, true);
    }

    function setPublished(uint256 listingId, bool published) external {
        AgentListing storage listing = listings[listingId];
        require(listing.provider != address(0), "AgentMarketplace: unknown listing");
        require(
            msg.sender == listing.provider || msg.sender == owner(),
            "AgentMarketplace: not authorized"
        );
        listing.published = published;
        emit AgentPublished(listingId, published);
    }

    function purchaseAccess(uint256 listingId) external payable {
        AgentListing storage listing = listings[listingId];
        require(listing.provider != address(0), "AgentMarketplace: unknown listing");
        require(listing.published, "AgentMarketplace: not published");
        require(msg.value >= listing.priceWei, "AgentMarketplace: underpayment");
        require(!hasAccess[msg.sender][listingId], "AgentMarketplace: already owned");

        hasAccess[msg.sender][listingId] = true;
        listing.totalPurchases += 1;

        (bool ok, ) = payable(listing.provider).call{value: listing.priceWei}("");
        require(ok, "AgentMarketplace: provider payout failed");

        if (msg.value > listing.priceWei) {
            uint256 refund = msg.value - listing.priceWei;
            (bool refundOk, ) = payable(msg.sender).call{value: refund}("");
            require(refundOk, "AgentMarketplace: refund failed");
        }

        emit AgentAccessPurchased(
            listingId,
            msg.sender,
            listing.provider,
            listing.priceWei,
            block.timestamp
        );
    }

    function canAccess(address account, uint256 listingId) external view returns (bool) {
        return hasAccess[account][listingId];
    }
}
