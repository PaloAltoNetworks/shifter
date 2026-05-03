configure

set profiles virus Alert-Only-AV decoder http action alert
set profiles virus Alert-Only-AV decoder ftp action alert
set profiles virus Alert-Only-AV decoder smb action alert
set profiles virus Alert-Only-AV decoder smtp action alert
set profiles virus Alert-Only-AV decoder imap action alert
set profiles virus Alert-Only-AV decoder pop3 action alert

set profiles spyware Alert-Only-AS description "Alert only for all severity levels"
set profiles spyware Alert-Only-AS rules Alert-All action alert
set profiles spyware Alert-Only-AS rules Alert-All severity any
set profiles spyware Alert-Only-AS rules Alert-All threat-name any
set profiles spyware Alert-Only-AS rules Alert-All category any

set profiles url-filtering Alert-Only-URL description "Alert on major threat categories"
set profiles url-filtering Alert-Only-URL category command-and-control action alert
set profiles url-filtering Alert-Only-URL category malware action alert
set profiles url-filtering Alert-Only-URL category phishing action alert
set profiles url-filtering Alert-Only-URL category grayware action alert
set profiles url-filtering Alert-Only-URL category ransomware action alert

set profiles file-blocking Alert-Only-FB description "Alert on all file types"
set profiles file-blocking Alert-Only-FB rules Alert-All action alert
set profiles file-blocking Alert-Only-FB rules Alert-All application any
set profiles file-blocking Alert-Only-FB rules Alert-All file-type any
set profiles file-blocking Alert-Only-FB rules Alert-All direction both

set profiles wildfire-analysis Alert-Only-WF description "Forward all files for analysis"
set profiles wildfire-analysis Alert-Only-WF rules Forward-All application any
set profiles wildfire-analysis Alert-Only-WF rules Forward-All file-type any
set profiles wildfire-analysis Alert-Only-WF rules Forward-All direction both
set profiles wildfire-analysis Alert-Only-WF rules Forward-All analysis public-cloud

set profiles vulnerability Alert-Only-VP rules Alert-All action alert
set profiles vulnerability Alert-Only-VP rules Alert-All severity any
set profiles vulnerability Alert-Only-VP rules Alert-All threat-name any
set profiles vulnerability Alert-Only-VP rules Alert-All category any
set profiles vulnerability Alert-Only-VP rules Alert-All cve any
set profiles vulnerability Alert-Only-VP rules Alert-All host any
set profiles vulnerability Alert-Only-VP rules Alert-All vendor-id any

set profile-group Alert-Group virus Alert-Only-AV
set profile-group Alert-Group spyware Alert-Only-AS
set profile-group Alert-Group vulnerability Alert-Only-VP
set profile-group Alert-Group url-filtering Alert-Only-URL
set profile-group Alert-Group file-blocking Alert-Only-FB
set profile-group Alert-Group wildfire-analysis Alert-Only-WF

set network profiles zone-protection-profile Alert-Only-ZP flood tcp-syn enable yes
set network profiles zone-protection-profile Alert-Only-ZP flood tcp-syn action alert
set network profiles zone-protection-profile Alert-Only-ZP flood udp enable yes
set network profiles zone-protection-profile Alert-Only-ZP flood udp action alert
set network profiles zone-protection-profile Alert-Only-ZP flood icmp enable yes
set network profiles zone-protection-profile Alert-Only-ZP flood icmp action alert

set zone ranges network zone-protection-profile Alert-Only-ZP

commit
