# Operation NORTHSTORM -- Narrative Design

---

## The World

### Joint Task Force POLARIS

JTF-POLARIS is Canada's ghost. It has no website, no recruiting office, no entry in the federal budget. It was stood up during the Cold War under a cabinet directive that has never been declassified, and it has operated continuously since -- through the fall of the Soviet Union, through 9/11, through the rise of state-sponsored cyber warfare. It answers to a single unnamed official in the Privy Council. Its operators are drawn from every branch of the Canadian security establishment, but once you're in POLARIS, that's your only allegiance.

POLARIS doesn't do policy. It doesn't do intelligence estimates. It does operations -- the ones that can't be attributed, can't be acknowledged, and can't fail.

Tonight, every participant in the room is a POLARIS operator. Some are veterans. Some are fresh activations who've never run an op. Doesn't matter. Everyone's in.

### AURORA COLLECTIVE

The adversary. AURORA COLLECTIVE is an advanced persistent threat group that has been on POLARIS's radar for years. They operate like a state actor but don't belong to any state. They have deep funding, sophisticated technical capabilities, and a pattern of acquiring weapons technology from multiple nations -- stealing, buying, or developing it themselves.

AURORA COLLECTIVE doesn't sell what they build. They don't broker. They build for themselves, and what they're building has been getting more ambitious. Six months ago, HUMINT assets reported that AURORA had moved from acquiring existing weapons platforms to developing something original. Something large. Something no one has seen before.

### Site BOREAS

AURORA COLLECTIVE's crown jewel. A compound in a denied-access region -- part corporate campus, part fortress, part underground manufacturing facility. On the surface it looks like a technology consultancy. Satellite imagery shows office buildings, a parking lot, a cafeteria. Normal enough.

But the footprint doesn't match the story. The power draw is enormous -- industrial scale, not office scale. Thermal imaging shows heat signatures underground that are consistent with heavy manufacturing. Truck traffic in and out carries components that don't match any known commercial product. And the security posture is wildly disproportionate to a tech company: dedicated security network, armed guards, electronic access control on every door, and an underground section that doesn't appear on any building permit.

Eighteen months of passive collection have given POLARIS a picture of the facility. Not complete, but enough to plan.

---

## The Facility

Site BOREAS is four places layered on top of each other. Each has its own character, its own people, its own secrets.

### The Front Office

The cover story. AURORA COLLECTIVE operates a legitimate technology consultancy called **Boreas Systems** out of the surface buildings. It has employees, clients, projects, an HR department, a mail server. Most of the people working here don't know what's underneath them. They're real employees doing real consulting work, and their IT infrastructure is real -- email, file shares, web applications, the usual enterprise sprawl.

But Boreas Systems is also where AURORA hides in plain sight. The employee database includes people whose roles don't match any consulting project. The procurement system shows purchase orders for components that have nothing to do with software. Internal emails between senior staff reference "the project" in ways that don't add up. The Front Office is a goldmine of intelligence for anyone who knows what to look for -- personnel records, supplier chains, internal communications, stored credentials that were never meant to leave the building.

The Front Office is the most exposed part of the facility. It faces the internet. It has the weakest security posture. It's where the operation begins.

### The Watchtower

Site BOREAS takes physical security seriously. There's a dedicated security operations center running CCTV, electronic access control, intrusion detection, and guard coordination. This is the Watchtower -- a separate network from the corporate IT, staffed by a separate team, running purpose-built systems.

The Watchtower sees everything. Every hallway, every entrance, every approach to the facility. It controls every door. It knows where every badge-holder is at any given moment. And critically, it has cameras covering the one thing that matters most: **the entrance to the underground complex.**

AURORA knows the underground facility is the thing worth protecting. The Watchtower exists primarily to keep unauthorized people away from what's below. If POLARIS wants to get into the underground, the Watchtower has to go blind first. Otherwise, whatever's down there stays unreachable.

### The Lab

Behind the consulting cover, AURORA COLLECTIVE runs a serious research and development operation. The Lab is where the actual science happens -- design work, engineering, simulation, testing. It's on its own network, segmented from both the Front Office and the Watchtower, and the people who work here are AURORA's true believers. They know exactly what they're building.

The Lab is where PROJECT LEVIATHAN lives as a concept -- as blueprints, as simulation models, as engineering specifications, as test data. The physical thing is being assembled underground, but the intellectual architecture of the weapon exists here. Design documents describe subsystems. Simulation logs show tests being run. Source code repositories contain the control software. Research notes reference milestones: "locomotion test successful," "actuator stress tolerance exceeded targets," "weapons integration on schedule."

The data is compartmentalized. No single system contains the full picture. A researcher working on hydraulics doesn't have access to the weapons specifications. The simulation team doesn't see the manufacturing schedules. AURORA has been careful about this -- they know the research data is the most valuable intelligence in the facility, and they've structured access so that compromising one system doesn't reveal everything.

But fragments add up. A hydraulic spec here, a stress test there, a simulation log showing something enormous taking a step forward. Enough fragments, from enough systems, and the picture starts to form.

### The Bunker

Beneath Site BOREAS, carved into bedrock, is the manufacturing complex. This is where PROJECT LEVIATHAN is being physically assembled. The Bunker is air-gapped -- there is no network connection to anything above ground. No cable, no wireless, no path. AURORA built it this way deliberately. The most sensitive work happens in a space that cannot be reached through cyberspace.

The Bunker runs on industrial control systems -- PLCs, motor controllers, hydraulic actuators, sensor arrays, and a central computer that orchestrates the manufacturing process. These systems speak OT protocols: Modbus, proprietary controller languages, bare-metal interfaces. They're designed for manufacturing, not for IT, and they have the security posture of systems that were never meant to be on a network anyone could reach.

The only way into the Bunker is physical. Someone has to go in -- through the entrance that the Watchtower guards, past the access control systems, down into the underground. And once they're there, they need to establish a communications path back to the outside so that POLARIS operators can reach the OT systems remotely.

This is where the special operations teams come in. JTF-2 -- Canada's tier-one special forces -- can insert a team into the underground if the conditions are right. They can carry a covert relay, patch it into the facility's internal wiring, and give POLARIS a narrow, fragile network path into the Bunker's control systems. But JTF-2 won't go in blind. They need the cameras down. They need to know the guard patterns. They need the approach to be clean. The Watchtower has to fall before the Bunker can open.

---

## PROJECT LEVIATHAN

### What POLARIS Knows (At Mission Start)

Almost nothing. An internal codename -- PROJECT LEVIATHAN -- found in intercepted communications. References to a "platform" nearing "operational readiness." Component shipments that suggest something large and mechanical. Power consumption consistent with heavy automated manufacturing. That's it. POLARIS doesn't know what it is, how big it is, what it does, or how close it is to completion.

Determining the nature of PROJECT LEVIATHAN is the central question of the operation.

### What the Operation Reveals (Progressively)

The answer doesn't come all at once. It comes in fragments, from different parts of the facility, and it only makes sense when the pieces are assembled.

**From the Front Office**: Procurement records show bulk orders of hydraulic actuators, high-torque servo motors, exotic alloys rated for extreme stress, industrial-scale power systems. This is not a vehicle. This is not a building. The scale and specifications don't match anything commercially manufactured.

**From the Lab**: Design documents describe subsystems -- "locomotion assembly," "stabilization array," "primary effector system." Simulation logs show stress tests on something bipedal. Engineering notes reference center-of-gravity calculations for a structure over 100 meters tall. A simulation video, if recovered, shows a wireframe of something enormous taking its first step.

**From the Bunker**: The OT systems tell the story in hardware. The hydraulic assemblies control joints -- legs, arms. Motor controllers drive a tail. An actuator bank deploys dorsal plates. A plasma torch array, labeled "industrial cutting system" in the maintenance logs, is clearly a weapon. And at the center of it all, a master controller running autonomous navigation and combat AI.

### The Reveal

PROJECT LEVIATHAN is a 120-meter autonomous combat platform. It has legs, arms, a tail, armored dorsal plates, and a directed energy weapon system. It is powered by an onboard reactor and controlled by an autonomous combat AI.

It is, unmistakably, Mecha-Godzilla.

AURORA COLLECTIVE didn't steal existing weapons technology. They built something that shouldn't exist. And it's nearly complete.

---

## The Story Arc

### Act 1: The Briefing

The real-world threat briefing about offensive AI doubles as the narrative setup. Everything Brad presents -- AI agents conducting attacks, autonomous exploitation, the speed and scale of AI-driven threats -- is the world that POLARIS operates in. The briefing is real. The transition into the fiction is seamless:

*"You've just seen what these tools can do. Now you're going to use them. Welcome to POLARIS. You have a mission."*

The mission brief is delivered. The stakes are set. AURORA COLLECTIVE has a weapon, it's almost ready, and POLARIS is the only thing standing between them and operational deployment. Tonight, the operation goes live.

### Act 2: First Contact

The operation begins with the outermost layer of the facility. Operators make first contact with Site BOREAS -- probing the Front Office, mapping the enterprise, pulling threads. For many, this is their first time running an offensive cyber operation. The AI agent on their Kali box is their partner, their teacher, their tool.

Early discoveries come quickly. Employee names. Email addresses. A password left in a config file. The facility begins to take shape as a real place with real people. The story starts to feel tangible.

For experienced operators, the Front Office is a waypoint. They pass through quickly, collecting credentials and intelligence, eyes already on the deeper targets. The Watchtower. The Lab. The hints of something larger.

### Act 3: Deepening

The operation matures. Multiple lines of effort are running simultaneously. Some operators are deep in the security systems, working to take the Watchtower offline. Others are in the Lab, pulling research fragments, starting to see patterns that don't make sense yet. The Front Office continues to yield intelligence that feeds everything else.

The central tension builds: **what is PROJECT LEVIATHAN?** Fragments of information are accumulating. Procurement manifests. Engineering specifications. Simulation data. None of it makes sense individually. An order for hydraulic actuators rated for 200 tons of force. A stress test on a bipedal joint. A power system spec that would serve a small city.

The mystery is the engine of the middle act. Every piece of intelligence deepens the question.

And then the Watchtower falls. Cameras go dark. The entrance to the underground is unguarded. JTF-2 gets the green light.

### Act 4: The Bunker

A new world opens. The OT systems in the underground manufacturing complex are unlike anything the operators have seen above ground. Industrial protocols. Motor controllers. Hydraulic systems. Sensor arrays. It's a factory floor controlled by machines talking to machines.

As operators work through the Bunker's systems, each one reveals a piece of the weapon. The hydraulics move joints -- bipedal joints. The motor controllers stabilize a tail. An actuator bank deploys something along a spine. A plasma system, labeled for industrial cutting, is clearly a directed energy weapon.

The picture assembles. The room starts to realize what they're looking at. The fragments from the Lab -- the simulation of something taking a step, the stress tests on something 100 meters tall, the center-of-gravity calculations -- suddenly make sense.

### Act 5: LEVIATHAN

The full schematic comes together. PROJECT LEVIATHAN is revealed.

This isn't a missile. It isn't a drone swarm. It isn't a cyber weapon. It's a 120-meter autonomous combat platform with legs, arms, a tail, armored plating, and atomic breath. AURORA COLLECTIVE built Mecha-Godzilla.

The moment lands because the story earned it. Four hours of serious, technically grounded work -- real reconnaissance, real exploitation, real problem-solving -- built toward a reveal that is genuinely absurd. The contrast is the joke. The craft makes the payoff.

The final act of the operation: seize the brain. Take control of the central AI. If POLARIS can own the master controller, they own the weapon. Operation NORTHSTORM is complete.

---

## Narrative Threads

These are the story threads woven through the facility that build toward the reveal. They're not challenges or objectives -- they're the pieces of narrative that operators encounter as they work through the facility, regardless of where they are.

### The Employee Who Knows Too Much

Somewhere in the Front Office's email archives is a correspondence trail from a mid-level engineer who started asking questions. They noticed the procurement orders didn't match any client project. They asked their manager about it. The responses got increasingly evasive, then hostile. The last email in the thread is a termination notice. Their access was revoked, but their files are still on the server.

This thread gives the Front Office emotional weight. It's not just data -- it's a person who got too close to the truth.

### The Unreliable Guard

In the Watchtower's systems, guard rotation logs show one guard who has been accessing restricted areas outside their scheduled patrol. Security camera logs show brief gaps -- a camera turned off for two minutes, then back on. Someone inside the security team is either compromised or running their own agenda.

This thread adds texture to the Watchtower. The security team isn't monolithic. There are cracks.

### The Midnight Test

In the Lab's simulation archives, a series of test runs labeled "MIDNIGHT SERIES" stand out. They were run after hours, by a single user account, and they model full-system integration -- something the compartmentalized research teams shouldn't have access to. Someone in the Lab assembled the full picture on their own and ran a simulation of PROJECT LEVIATHAN at full operational capacity. The simulation succeeded.

This thread tells operators that the weapon works. It's not theoretical. It's been tested, at least in simulation.

### The Shipping Manifest

The procurement system in the Front Office contains a shipping manifest for a delivery that hasn't arrived yet. It's scheduled for next week. The contents: a reactor core. The delivery address: a location within the facility that doesn't appear on any floor plan.

This thread establishes urgency. The weapon is almost complete. The reactor is the last piece. If it arrives, PROJECT LEVIATHAN goes operational.

### Assembly Log

On the Bunker's central monitoring system, an assembly log tracks the status of PROJECT LEVIATHAN's construction. Most entries read "COMPLETE." Locomotion: complete. Stabilization: complete. Weapons integration: complete. Armor: complete. One entry reads "PENDING: Primary power source." One reads "PENDING: Autonomous control activation."

The weapon is waiting for its heart and its brain. The reactor arrives next week. The control AI is in the system right now, dormant, waiting for power.

---

## Tone

### The Serious Parts

The operation, the tradecraft, the technical work -- all of this is played straight. The mission brief reads like a real intelligence product. The facility's internal documents read like a real defense contractor's files. The engineering specifications are plausible. The attack techniques are real. At no point does the narrative wink at the audience or break the fourth wall.

This matters because the payoff depends on it. If the whole thing is a joke from the start, the reveal is just another joke. If the whole thing is dead serious until the moment the schematic assembles, the reveal is unforgettable.

### The Absurd Part

Mecha-Godzilla. That's it. That's the one absurd element, and it's held back until the very end. Everything before it is grounded. The absurdity is concentrated in a single moment of realization, and it works because the audience did real work to get there.

Don't over-explain it. Don't lampshade it. Don't have an NPC say "can you believe it's a giant robot?" The schematic appears. The shape is unmistakable. The room does the rest.

### The In-Between

The facility's internal culture should feel like a real workplace that happens to be building something monstrous. Employees complain about parking. The cafeteria menu is on the intranet. Someone left a passive-aggressive note about the coffee machine. The mundanity makes the horror (and the comedy) of what's underneath more effective.

AURORA COLLECTIVE isn't staffed by Bond villains. It's staffed by engineers, administrators, guards, and researchers who go home at the end of the day. Most of them probably don't know the full picture. The ones who do have rationalized it. The banality is the point.

---

## The Operation as Collaborative Story

The most important narrative design principle: **every operator is part of the story, and the story is shaped by what they do.**

An operator who spends the whole event in the Front Office, pulling personnel records and reading emails, has experienced the story of AURORA COLLECTIVE's cover operation -- the mundane face of something terrible. They've seen the employee who asked too many questions. They've found the procurement orders that don't add up. They've contributed intelligence that helped the operation succeed.

An operator who pushed through the Watchtower and opened the path to the Bunker has experienced the story of breaching a fortress -- taking down the eyes and ears of a security apparatus that was built to be impenetrable.

An operator who fought through the Bunker and seized the brain has experienced the story of discovering and neutralizing a weapon that shouldn't exist.

These are different stories, but they're all part of the same operation. The narrative holds together because the facility is a coherent place, the adversary is a coherent organization, and the mystery at the center -- what is PROJECT LEVIATHAN? -- is a question that everyone's work contributes to answering.

Nobody is a side character. Everyone is POLARIS.
