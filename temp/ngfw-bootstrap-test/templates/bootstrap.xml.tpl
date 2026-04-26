<?xml version="1.0"?>
<config version="11.2.0" urldb="paloaltonetworks">
  <mgt-config>
    <users>
      <entry name="admin">
        <phash>${admin_password_hash}</phash>
        <permissions>
          <role-based>
            <superuser>yes</superuser>
          </role-based>
        </permissions>
      </entry>
    </users>
  </mgt-config>
  <devices>
    <entry name="localhost.localdomain">
      <deviceconfig>
        <system>
          <hostname>ngfw-test</hostname>
        </system>
        <setting/>
      </deviceconfig>
      <network>
        <interface>
          <ethernet>
            <entry name="ethernet1/1">
              <layer3>
                <dhcp-client>
                  <enable>yes</enable>
                  <create-default-route>no</create-default-route>
                </dhcp-client>
              </layer3>
            </entry>
          </ethernet>
        </interface>
        <virtual-router>
          <entry name="default">
            <interface>
              <member>ethernet1/1</member>
            </interface>
          </entry>
        </virtual-router>
      </network>
      <vsys>
        <entry name="vsys1">
          <import>
            <network>
              <interface>
                <member>ethernet1/1</member>
              </interface>
            </network>
          </import>
          <zone>
            <entry name="ranges">
              <network>
                <layer3>
                  <member>ethernet1/1</member>
                </layer3>
              </network>
            </entry>
          </zone>
        </entry>
      </vsys>
    </entry>
  </devices>
</config>
