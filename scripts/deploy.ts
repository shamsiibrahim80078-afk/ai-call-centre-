import { ethers } from "hardhat";
import hre from "hardhat";
import * as fs from "fs";
import * as path from "path";

export type DeploymentRecord = {
  token_name: string;
  token_symbol: string;
  contract_address: string;
  network: string;
  tx_hash: string;
  deployed_at: string;
  contract_name: string;
};

function networkLabel(name: string): string {
  const map: Record<string, string> = {
    hardhat: "Hardhat",
    localhost: "Hardhat",
    sepolia: "Sepolia",
    base: "Base",
    ethereum: "Ethereum",
    mainnet: "Ethereum",
  };
  return map[name] || name;
}

export async function deployWorkforceStack(): Promise<DeploymentRecord[]> {
  const [deployer] = await ethers.getSigners();
  const network = await ethers.provider.getNetwork();
  const resolvedNetwork = networkLabel(hre.network.name);
  const deployedAt = new Date().toISOString();
  const records: DeploymentRecord[] = [];

  console.log(`Deployer: ${deployer.address}`);
  console.log(`Network: ${resolvedNetwork} chainId=${network.chainId}`);

  const initialSupply = ethers.parseEther("1000000");

  const Token = await ethers.getContractFactory("WorkforceToken");
  const token = await Token.deploy("Workforce Token", "WORK", initialSupply, deployer.address);
  await token.waitForDeployment();
  const tokenTx = token.deploymentTransaction();
  records.push({
    token_name: "Workforce Token",
    token_symbol: "WORK",
    contract_address: await token.getAddress(),
    network: resolvedNetwork,
    tx_hash: tokenTx?.hash || "0x0",
    deployed_at: deployedAt,
    contract_name: "WorkforceToken",
  });
  console.log(`WorkforceToken -> ${records[0].contract_address}`);

  const Treasury = await ethers.getContractFactory("WorkforceTreasury");
  const treasury = await Treasury.deploy(deployer.address);
  await treasury.waitForDeployment();
  const treasuryTx = treasury.deploymentTransaction();
  records.push({
    token_name: "Workforce Treasury",
    token_symbol: "TREASURY",
    contract_address: await treasury.getAddress(),
    network: resolvedNetwork,
    tx_hash: treasuryTx?.hash || "0x0",
    deployed_at: deployedAt,
    contract_name: "WorkforceTreasury",
  });
  console.log(`WorkforceTreasury -> ${records[1].contract_address}`);

  const Subscription = await ethers.getContractFactory("SubscriptionManager");
  const subscription = await Subscription.deploy(deployer.address);
  await subscription.waitForDeployment();
  const subTx = subscription.deploymentTransaction();
  records.push({
    token_name: "Subscription Manager",
    token_symbol: "SUB",
    contract_address: await subscription.getAddress(),
    network: resolvedNetwork,
    tx_hash: subTx?.hash || "0x0",
    deployed_at: deployedAt,
    contract_name: "SubscriptionManager",
  });
  console.log(`SubscriptionManager -> ${records[2].contract_address}`);

  const Marketplace = await ethers.getContractFactory("AgentMarketplace");
  const marketplace = await Marketplace.deploy(deployer.address);
  await marketplace.waitForDeployment();
  const mktTx = marketplace.deploymentTransaction();
  records.push({
    token_name: "Agent Marketplace",
    token_symbol: "AGNT",
    contract_address: await marketplace.getAddress(),
    network: resolvedNetwork,
    tx_hash: mktTx?.hash || "0x0",
    deployed_at: deployedAt,
    contract_name: "AgentMarketplace",
  });
  console.log(`AgentMarketplace -> ${records[3].contract_address}`);

  const outDir = path.join(__dirname, "..", "deployments");
  fs.mkdirSync(outDir, { recursive: true });
  const outFile = path.join(outDir, `${resolvedNetwork}-latest.json`);
  fs.writeFileSync(
    outFile,
    JSON.stringify(
      {
        network: resolvedNetwork,
        chainId: Number(network.chainId),
        deployer: deployer.address,
        deployed_at: deployedAt,
        contracts: records,
      },
      null,
      2
    )
  );
  console.log(`Wrote ${outFile}`);
  return records;
}

async function main() {
  await deployWorkforceStack();
}

if (require.main === module) {
  main().catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
}
