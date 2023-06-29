import time
import asyncio
import base64

from io import BytesIO

from aiohttp_xmlrpc.client import ServerProxy
import math
import numpy as np
from numpy.lib import format as npf

from matplotlib.backends.qt_compat import QtWidgets, QtCore

Freq = float

class SampleBuffer:
    def __init__(self, server, n, direction="input"):
        self.sample_rate = 2e9
        self.direction = direction
        self.server = server
        self.n = n
        self.N = -1
        self.samples = [ 0 ] * 4096
        self.compute()

    
        
    async def update(self):
        try:
            wire_samples = await self.server.get_samples(self.direction, self.n)
        
            self.samples = npf.read_array(BytesIO(base64.b64decode(wire_samples)))
            self.compute()
        except ConnectionRefusedError:
            self.samples = [ 0 ] * 4096
            self.compute()
            
        return True
        
    def compute(self):
        self.N = len(self.samples)
        self.t = np.arange(0, self.N) / self.sample_rate
        self.f = np.fft.fftshift(np.fft.fftfreq(self.N)) * self.sample_rate

        self.fft = np.abs(np.fft.fftshift(np.fft.fft(self.samples))) / self.N
        
        self.fft[self.fft == 0] = 1e-100
        #self.dB = 10 * np.log10(self.fft)
        self.dB = np.nan_to_num(10 * np.log10(self.fft), nan=-100, posinf=100, neginf=-100)
        
    async def one_shot(self, b):
        await self.server.one_shot(self.n, self.direction, b)

    async def set_samples(self, v):
        assert self.direction == 'output', "Setting samples is not allowed for input samples"
        f = BytesIO()

        npf.write_array(f, v)

        self.samples = v

        await self.server.set_samples(self.n, base64.b64encode(f.getvalue()))

    async def fill_dc(self, level):
        v = np.ones(self.nsamples) * level
        
        await self.set_samples(v)
        
    async def fill_sine(self, freq, phase=0.0):
        phase_advance = 2 * math.pi * freq / self.sample_rate
        phi = phase
        
        v = np.arange(0, self.nsamples) * phase_advance + phase
        v = np.sin(v) - 1.0j * np.cos(v)

        await self.set_samples(v)

    def fill_chirp(self, freqA: Freq, freqB: Freq, phase : float = 0, N : int=1):
        if self.samples._format == IQ_SAMPLES:
            T = self.T / N
            
            c = (freqB - freqA) / T        
            t = np.arange(0, self.nsamples / N) / self.sample_rate

            t = np.tile(t, N)
            
            phi = phase + 2 * np.pi * (t * c + freqA) * t
            
            v = (np.sin(phi) - 1.0j * np.cos(phi)) * 0x7FFF
            
            for i, x in zip(range(self.start_sample, self.end_sample), v):
                self.samples[i] = (int(x.real), int(x.imag))
        else:
            raise RuntimeException("Not implemented")

        
    def fill_Zadoff_Chu(self, Nzc : int, u : int, q : int):
        c_f = Nzc & 1

        a = np.arange(0, Nzc)

        seq = 0x7FFF * np.exp(-1.0j * np.pi * u * a * (a + c_f + 2 * q) / Nzc)

        for i, v in enumerate(seq):
            self.samples[self.start_sample + i] = (int(v.real), int(v.imag))
        
        for i in range(self.start_sample + Nzc, self.end_sample):
            self.samples[i] = (0,0)

    fill_zc = fill_Zadoff_Chu
        
    @property
    def nsamples(self):
        if not hasattr(self, "samples"):
            self.update()

        return len(self.samples)

class TaskGroup:
    pass
    
class UpdateWorker(QtCore.QObject):
    data_ready = QtCore.pyqtSignal()
    
    def __init__(self, app, server_uri):
        self.app = app
        self.uri = server_uri
        super().__init__()

        self.server = ServerProxy(server_uri)
        
        self.input_samples = [ SampleBuffer(self.server, n, "input") for n in range(8) ]
        self.output_samples = [ SampleBuffer(self.server, n, "output") for n in range(8) ]

        self.stop_ack = asyncio.Event()
        self.stop_req = False

    def start(self):
        self.task = asyncio.create_task(self.update_task())
        return self.task
    
    def stop(self):
        self.task.cancel()

    async def stopped(self):
        await self.stop_ack.wait()
        self.server.close()
        
    async def update_once(self):
        outstanding = set()

        await self.server.global_trigger()
        
        for buf in self.input_samples:
            t = asyncio.create_task(buf.update())
            outstanding.add(t)
            t.add_done_callback(outstanding.discard)

        
        await asyncio.wait(outstanding)            
        
    async def update_task(self):
        outstanding = set()

        # Automatically set to one shot sampling
        for buf in self.input_samples:
            t = asyncio.create_task(buf.one_shot(True))
            outstanding.add(t)
            t.add_done_callback(outstanding.discard)        

        await asyncio.wait(outstanding)            
            
        outstanding = set()
        
        # Automatically set to continuous streaming
        for buf in self.output_samples:
            t = asyncio.create_task(buf.one_shot(False))
            outstanding.add(t)
            t.add_done_callback(outstanding.discard)        

        await asyncio.wait(outstanding)            

        outstanding = set()
                    
        for buf in self.output_samples:
            t = asyncio.create_task(buf.update())
            outstanding.add(t)
            t.add_done_callback(outstanding.discard)        

        await asyncio.wait(outstanding)            

        for t in outstanding:
            if t.result != True:
                print("Failed to update buffer")
                
        
        while self.stop_req == False:
            await self.update_once()
            
            self.data_ready.emit()

            await asyncio.sleep(0.5)

        self.stop_ack.set()
