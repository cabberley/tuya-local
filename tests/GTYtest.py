import tinytuya
import time

# Zigbee Gateway support uses a parent/child model where a parent gateway device is
#  connected and then one or more children are added.

# configure the parent device
gw = tinytuya.Device( 'bfe9e9ecd599bebd34tihc', address='192.168.5.156', local_key='7bd96fc2381cf321', persist=True, version=3.3 )

print( 'GW IP found:', gw.address )

# configure one or more children.  Every dev_id must be unique!
#zigbee1 = tinytuya.OutletDevice( dev_id='bf8cf0adfe86bf3852htld', cid='02d0', parent=gw )
zigbee2 = tinytuya.BulbDevice( dev_id='bf8cf0adfe86bf3852htld', cid='02d0', parent=gw )
#zigbee2 = tinytuya.OutletDevice( 'eb04...l', cid='0011223344556689', parent=gw )
#zigbee1 = tinytuya.OutletDevice()

print(zigbee2.status())
#print(zigbee2.status())

print(" > Begin Monitor Loop <")
pingtime = time.time() + 9

while(True):
    if( pingtime <= time.time() ):
        payload = gw.generate_payload(tinytuya.HEART_BEAT)
        gw.send(payload)
        pingtime = time.time() + 9

    # receive from the gateway object to get updates for all sub-devices
    print('recv:')
    data2 = zigbee2.colour_rgb()
    data = gw.receive()
    print( data )
    zigbee2.set_colour(0,255,0)

    # data['device'] contains a reference to the device object
    #if data and 'device' in data and data['device'] == zigbee2:
    if zigbee2 == zigbee2:
        print('toggling device state')
        zigbee2.turn_off(switch=1)
        time.sleep(3)
        #if data['dps']['1']:
        #    data['device'].turn_off(nowait=True)
        #else:
        #    data['device'].turn_on(nowait=True)
        zigbee2.turn_on(switch=1)