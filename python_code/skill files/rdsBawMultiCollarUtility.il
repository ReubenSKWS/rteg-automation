procedure(rdsBawMultiCollar(cellId objA devType clrAngsNew lyr nc adr mbeoffset collarAngle mteClrW mbeClrW @key (collarEnc  -1.0) (orawMkr nil) )
	prog(  (mbepzzl m1sv mtem1 mtesv aascl sclpzl adrDiff kpEclr collarMBE collarMTE  y0Eclr steEmte 
			obj1 obj2 obj3 obj4 obj5 obj6 points ang0 ang1 ang2 ang3 p0a p1a p2a p3a p0 
			crsPts10 crsPts11 crsPts12 crsPts13 crsPtsList clrPts i pdpt sgn angl pdpt1 pdpt2 pdpt0 
			colLen times  pdpt1Ext pdpt2Ext pdl pdl1 pdl2 pdl0 bln1a bln1b bln2a bln2b crs1 crs2 
			bbxobj4 canPts l0Ext l1Ext l2Ext l3Ext l0 l1 l2 l3 l023 lclrPt0 lclrPt1 lclrPt2 lclrPt3 litr 
			lclrCrs times rclrPt0 rclrPt1 rclrPt2 rclrPt3 rclrcrs ritr lclrang1 lclrAng2 rclrAng1 rclrAng2 
			ptl bbxPts obj4bbxLines bline llineCrs lcart lpol rcart rpol lclrPtsList rclrptsList pt ll rr 	
			shp1 shp2 obj MBElines MTElines shpOut mbeOut mteClrShp mbeClrShp clrcrs1 clrcrs2 mbecrs1 mbecrs2 	
			inst steClr steShp ctlp0 ctlp2 ctlp4 ctlp6 ctl1 ctl2 ctl	m1Eclrm1sv m1Clr_old svClr	m1Out ClrShp m1Eclr	m1Clr)
	

		if(adr  then
	        ;;mbepzl = 2.0
	        mbepzl = 0.8
            m1sv = 2.0          ;;updated according to JH 01/11
            mtem1 = 2.0
            mtesv = 2.0
;;            aascl = 4.0
            aascl = 5.0         ;;updated according to Matt 01/11
            sclpzl = 1.5
            adrDiff = 2.5
            kpEclr = 7.0
	    else
	        mbepzl = 4.0
	        m1sv = 2.0
	        mtem1 = 3.0
	        mtesv = 3.5	 
	        aascl = 5.0 
            sclpzl = 2.0             
            adrDiff = 0.0 
            kpEclr = 8.0
	    )
		if( mbeoffset then 
            collarMBE = mbepzl +  aascl + sclpzl-1.0 
        else
            ;;collarMBE = mbepzl +  aascl + sclpzl
            collarMBE = evalstring(mbeClrW)
            if(evalstring(mbeClrW) == 0 then collarMBE = 7.3)
        );;if
        ;;collarMTE = 9.0-(2.0-m1sv)-(3.5-mtesv)   ;;mte collar outter edge changed with m1sv (no change is m1sv = 2)
        collarMTE = evalstring(mteClrW)
        if(evalstring(mteClrW) == 0 then collarMTE = 5.3)

		m1Eclrm1sv = mtem1
		m1Emte 	  = 3.5
		m1Embe 	  = 3.5		
		pzlEclrEdge	  = 4.0
		pzlEMTE = 14.0-adrDiff		
			
		y0Eclr = 40.0 
        steEmte = 4.0    
        steEaa = 6.8      
        
        svEncAA = 5.5
        
        if(lyr == "BAW_MBE" then 
			clrType = "MBE" 
			m1Eclr = m1Embe
			clrW = collarMBE
		else
			if(lyr == "BAW_MTE" then
				clrType = "MTE"
			else
				clrType = "Clr"
			);;if
			m1Eclr = m1Emte
			clrW = collarMTE
		);;if

    ;;;;;;;;;;;;collars;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;; 
  		;;size up AA to collar and EM ruler   
		obj1 = dbLayerSize( cellId "text"      objA collarEnc nc*2)
		obj5 = dbLayerSize( cellId "text"      objA collarEnc-0.2 nc*2)
		refObj  = dbLayerSize( cellId "BAW_LABEL" objA clrW nc*2 )
		obj3  = dbLayerSize( cellId "pin"       objA collarMBE nc*2 )	
		obj4 = dbLayerSize( cellId "BAW_H1"    objA y0Eclr	  nc*2 )	
		obj6 = dbLayerSize( cellId "BAW_H2"      objA 1.0 nc*2)
		obj7 = dbLayerSize( cellId "BAW_H2"      objA svEncAA nc*2)
		points = car(obj3)~>points
		

	    ang0 = nth(0 clrAngsNew)                  
	    ang1 = nth(1 clrAngsNew) 
	    dang = abs(ang1-ang0)*0.05
	    
    
		;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
		;;;;;;;step1. get basic 45 degree lines;;;;;;;;;;;;;;;;;;;;;;;;;
		;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
	    ;;get intersection points with angle in AA
	    p0a = rdsBawXmlUserClrFindCrossingPointByAngle( objA  ang0)
	    p1a = rdsBawXmlUserClrFindCrossingPointByAngle( objA  ang1)
	    
	    p0b = rdsBawXmlUserClrFindCrossingPointByAngle( objA  ang0+dang)
	    p1b = rdsBawXmlUserClrFindCrossingPointByAngle( objA  ang1-dang)
		
		;;add text label for angle and direction collar would go when increase angle
		dbCreateLabel(cellId  "text" p0a sprintf(nil "%A" ang0) "centerCenter"  "R0"  "stick" 2.0 )
		dbCreateLabel(cellId  "text" p1a sprintf(nil "%A" ang1) "centerCenter"  "R0"  "stick" 2.0 )
		dbConvertPathToPolygon(dbCreatePath(cellId "text" list(p0a p0b) 0.04))
		dbConvertPathToPolygon(dbCreatePath(cellId "text" list(p1a p1b) 0.04))
		tri0 = rdsBawSkinnyRotateLine(p0a p0b 90.0  car(centerBox(list(p0a p0b))) cadr(centerBox(list(p0a p0b))) )	
		tri1 = rdsBawSkinnyRotateLine(p1a p1b 90.0  car(centerBox(list(p1a p1b))) cadr(centerBox(list(p1a p1b))))	
		tri0Pts = list( centerBox(list(car(tri0) p0b)) p0b  centerBox(list(cadr(tri0) p0b))  )
		tri1Pts = list( centerBox(list(car(tri1) p1a)) p1a  centerBox(list(cadr(tri1) p1a))  )
		dbConvertPathToPolygon(dbCreatePath(cellId "text" tri0Pts 0.04))
		dbConvertPathToPolygon(dbCreatePath(cellId "text" tri1Pts 0.04))
	    
	    p0 = list(0.0 0.0)
	    ;;times = max(2.0 min(dist(p0 p0a) dist(p0 p1a) )/collarMBE)
 
	
		;;get intersection points and line segment in obj1 by line (0:0 pxa)  
		;;pts 0, 2, 4, 6 in the slides  
		crsPts10 = rdsBawFindPolygonIntersectionPoints(car(obj1) list(p0 p0a))
		crsPts11 = rdsBawFindPolygonIntersectionPoints(car(obj1) list(p0 p1a))
		crsPtsList = list(crsPts10 crsPts11)
		
		
		clrPts = list()
		for(i 0 length(crsPtsList)-1
			pdpt = car(nth(i crsPtsList))
			if(oddp(i)  then
				sgn = 1.0
			else
				sgn = -1.0
			)
			angl = collarAngle*sgn
			pdpt1 = nth(1 pdpt)
			pdpt2 = nth(2 pdpt)
			pdpt0 = nth(0 pdpt)
			
			;;if dist from intersection point to any end of the intersection segment < collar*2, 
			;;		extend that end to dist = 2*collar, this ensure 45 degree rotation will cross AA and line long enough to create collar
			colLen = max(collarMBE collarMTE)*2.0
			if(dist(pdpt0 pdpt1)< colLen then 
				times = colLen/dist(pdpt0 pdpt1)
				pdpt1Ext = rdsBawSkinnyExtendPoints( pdpt0 pdpt1 times)
			else
				pdpt1Ext = pdpt1
			);;if
			
			if(dist(pdpt0 pdpt2)< colLen then 
				times = colLen/dist(pdpt0 pdpt2)
				pdpt2Ext = rdsBawSkinnyExtendPoints(pdpt0 pdpt2 times)
			else
				pdpt2Ext = pdpt2
			);;if


			;;foreach intersection segment line, rotate +/-45 degree 
			pdl = rdsBawSkinnyRotateLine(pdpt1Ext pdpt2Ext angl car(pdpt0)  cadr(pdpt0) )	
;dbCreateLine(cellId strcat("y" sprintf(nil "%d" i)) pdl)			
			pdl1 = car(pdl)
			pdl2 = cadr(pdl)
			pdl0 = pdpt0
			
;rdsBawCreateCircle(cellId  strcat("y" sprintf(nil "%d" i))  pdl0  1.0  10)	

		;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
		;;;;;;;step2. find inner point and outter point of the 45 degree line;;;;;;;;
		;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
			
			;;find 45 degree line outer end point
			;;if both ends are inside/on boundary of mbecollar shape, extend the line by 2 times
			;;else
			;;	if both ends are outside of the mbecollar shape, find the one not cross AA and use it
			;;	else
			;;		if one end inside and one end outside, use the outter points
			;;return clrPts = list( pdl00 pdlout0, pdl01 pdlout1,...)
			;;return pts (0 1) (2 3) (4 5) (6 7) in the slides
			;;if two lines points crossed, shorten it and use the cross point shrink 10% instead of the two outter points
			
			bln1a = rdsBawSkinnyPointInPolygon(pdl1 points) 
			bln1b = rdsBawPointOnBoundary(pdl1 points) 
			bln2a = rdsBawSkinnyPointInPolygon(pdl2 points)
			bln2b = rdsBawPointOnBoundary(pdl2 points)
			if( (bln1a || bln1b ) && (bln2a || bln2b) then
				pdl1 = rdsBawSkinnyExtendPoints( pdl2 pdl1 4.0)
				pdl2 = rdsBawSkinnyExtendPoints( pdl1 pdl2 4.0)		
				bln1a = rdsBawSkinnyPointInPolygon(pdl1 points) 
				bln1b = rdsBawPointOnBoundary(pdl1 points) 
				bln2a = rdsBawSkinnyPointInPolygon(pdl2 points)
				bln2b = rdsBawPointOnBoundary(pdl2 points)	
			);;if
			if(!bln1a && !bln1b && !bln2a && !bln2b then
				crs1 = rdsBawFindPolygonIntersectionPoints(car(obj5) list(pdl0 pdl1))
				crs2 = rdsBawFindPolygonIntersectionPoints(car(obj5) list(pdl0 pdl2))
				if(crs1 then clrPts = append(clrPts list(pdl0 pdl2)) )
				if(crs2 then clrPts = append(clrPts list(pdl0 pdl1)) )
			else
				if(!bln1a && !bln1b && (bln2a || bln2b ) then
					clrPts = append( clrPts list(pdl0 pdl1) )
				else
					if( (bln1a || bln1b) && !bln2a && !bln2b then
						clrPts = append( clrPts list(pdl0 pdl2) )
					);;if
				);;if
			);;if
		
		);;for
		
		;;mesh is reverse order of below (upper right -->lower right-->lower left-->upper left)
		ptl = list(nth(0 clrPts) nth(2 clrPts) )
		
		;;;;;;;;;;;;;;;;;;;;;Assumptions;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
		;;angle definition is counter clockwise
		;;angl0 -> angl1 so ang0 must < angl1, so angle 2 must < ang3
		;;so lclrAng1 < lclrAng2
		;;only exception will be when lclrAng1 is in quadrant 4 and lclrAng2 is in other quadrant
		;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
		
		;;add bbx coord to list
		;;extend lines and find intersection of line and bbx four edges, add to list
		;;convert to polar and compare
		
		l0Ext = rdsBawSkinnyExtendPoints( nth(0 clrPts) nth(1 clrPts) 100.0)
		l1Ext = rdsBawSkinnyExtendPoints( nth(2 clrPts) nth(3 clrPts) 100.0)

		l0 = list(nth(0 clrPts) l0Ext)
		l1 = list(nth(2 clrPts) l1Ext)

		l023 = list(l0 l1 )
		
		
		;;left collar are first 4 points, so connect with pdl01 pdl00 pdlout1 pdlout0
		;;right collar are 4~7 points, so connect with pdl02 pdl03 pdlout3 pdlout2
		;;when two collar line crossed, use crossing pt instead of the two outter points
		;;eg. line(pt0 pt1) and line(pt2 pt3) crossed, find intersection and use it shrink 10% instead of pt1 and pt3
		lclrPt0 = nth(0 clrPts)
		lclrPt1 = nth(1 clrPts)
		lclrPt2 = nth(2 clrPts)
		lclrPt3 = nth(3 clrPts)
		

		;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
		;;;;;;;step3. find angle range, sort helping points in order;;;;;;;;;;;;;;;;;
		;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;			
		;lclrAng1 = cadr(rdsBawCart2Pol(car(lclrPt1) cadr(lclrPt1)))
		;lclrAng2 = cadr(rdsBawCart2Pol(car(lclrPt3) cadr(lclrPt3)))


		bbxobj4 = car(rdsBawConvertBBXToPolygonXY(car(obj4)~>bBox))
		;;add obj4 bbx (AA size up 40), add crossing points
		bbxPts = list()
		obj4bbxLines = list(car(last(bbxobj4)) )
		obj4bbxLines = append(obj4bbxLines bbxobj4)
		for(i 0 length(l023)-1
			lline = nth(i l023)
			lchk = nil
			for(j 1 length(obj4bbxLines)-1 
				bline = list( nth(j-1 obj4bbxLines) nth(j obj4bbxLines) )
				llineCrs = rdsBawFindLineIntersectionPoints(lline bline)
				if(llineCrs && !lchk then bbxPts = append1(bbxPts llineCrs) lchk = t )
			);;forj	
		);;fori
		
		lclrCrs = rdsBawFindLineIntersectionPoints(list(lclrPt0  nth(0 bbxPts))  list(lclrPt2 nth(1 bbxPts)))
		lclrPts = list(lclrPt0 lclrCrs lclrPt2)
		
		lclrAng1 = cadr(rdsBawCart2Pol(car(nth(0 bbxPts)) cadr(nth(0 bbxPts))))
		lclrAng2 = cadr(rdsBawCart2Pol(car(nth(1 bbxPts)) cadr(nth(1 bbxPts))))
		
				
		;;add bbox and intersection with bbx, can be optimized to use only bbx and intersection between angle
		lcart = list()
		lcart = append(lcart bbxobj4)
		lcart = append(lcart bbxPts)
		lpol = rdsBawPolyCart2Pol(lcart)	
		

		lclrPtsList = list()

		foreach(pt lpol  
			if(lclrAng1 < lclrAng2 then
				if(cadr(pt)>= lclrAng1 && cadr(pt)<= lclrAng2 then lclrPtsList = append1(lclrPtsList pt) )  
			else
				if(cadr(pt)>= lclrAng1 || cadr(pt)<= lclrAng2 then lclrPtsList = append1(lclrPtsList pt) )  
			);;if
		);;foreach

			
		ll = rdsBawPolyPol2Cart(lclrPtsList)
		;;ll = append(list(lclrPt0  nth(0 bbxPts)) ll) 
		;;ll = append(ll  list(nth(1 bbxPts) lclrPt2) )
		;;05/26/2024, v0.21, updated by yangj1, fix outside polygon sequence issue
		if(member(nth(0 bbxPts) ll) then p0Ref = nth(0 bbxPts) else
			dmin = 1.0e10
			foreach(pt ll  dxy = dist(pt nth(0 bbxPts)) if(dxy < dmin then dmin = dxy, p0Ref = pt))
		);;if
		if(member(nth(1 bbxPts) ll) then p1Ref = nth(1 bbxPts) else
			dmin = 1.0e10
			foreach(pt ll  dxy = dist(pt nth(1 bbxPts)) if(dxy < dmin then dmin = dxy, p1Ref = pt))
		);;if
		p0Indx = lindex(ll p0Ref)-1
		p1Indx = lindex(ll p1Ref)-1
		lfinal = list()
		llnew = list()
		;;ll = list(1 2 3 4 5), suppose p0Ref and P1Ref is 2, 3, try to make p0ref and p1ref the first two ele in the list
		;;substitute p0ref p1ref with bbx0, p0, p2, bbx1/bbx1, p2, p0 bbx0 depends p0indx and p1indx 
		if(p0Indx < p1Indx then
			if(p1Indx == length(ll)-1 && p0Indx == 0 then
				;;llnew = append(last(ll) reverse(cdr(reverse(ll))))
				llnew = cdr(reverse(cdr(reverse(ll))))
				lfinal= append( list(nth(1 bbxPts) lclrPt2 lclrPt0 nth(0 bbxPts)  ) llnew)
			else
				for(i p1Indx+1 length(ll)-1 llnew = append1(llnew nth(i ll)))
				for(i 0 p0Indx-1 llnew = append1(llnew nth(i ll)))								
				lfinal = append( list(nth(0 bbxPts) lclrPt0 lclrPt2 nth(1 bbxPts)) llnew)
			);;if
			
		else
			if(p0Indx == length(ll)-1 && p1Indx == 0 then
				llnew = reverse(cdr(reverse(ll)))
				lfinal = append( list(nth(0 bbxPts) lclrPt0 lclrPt2 nth(1 bbxPts)) llnew)				
			else
				for(i p0Indx+1 length(ll)-1 llnew = append1(llnew nth(i ll)))
				for(i 0 p1Indx-1 llnew = append1(llnew nth(i ll)))				
				lfinal= append( list(nth(1 bbxPts) lclrPt2 lclrPt0 nth(0 bbxPts)  ) llnew)
				
			);;if
		);;if
		ll = lfinal
		
		;;;;;;;;;;;;;;basic polygon to create collars are done;;;;;;;;;;;;;;;;;;;;;;
		if(lclrCrs then 
			in1 = rdsBawSkinnyPointInPolygon(lclrCrs car(refObj)~>points) 
			on1 = rdsBawPointOnBoundary(lclrCrs car(refObj)~>points)
			if(in1 || on1  then
				error("Cut line angle is too close and it cross inside MBE/MTE collar, please reset the values.\n")
			else
				lcrsPts = lclrPts 
;dbCreatePolygon(cellId "y7"  lclrPts)	
			);;if 
		else 
			lcrsPts = ll 
;dbCreatePolygon(cellId "y7" ll)	
		);;if

		

		shpDonut = dbLayerAndNot( cellId lyr refObj obj1 nc*2 )


		foreach(obj obj1 dbDeleteObject(obj))  		
		foreach(obj obj5 dbDeleteObject(obj))   

		clrLines = list()

		shpOut = dbCreatePolygon(cellId "y1" lcrsPts )			
		ClrShp = dbLayerAnd(cellId lyr shpDonut list(shpOut) 2*nc)	
		
							
		
		clrcrs1 = rdsBawFindPolygonIntersectionPoints(car(refObj) l0)
		clrcrs2 = rdsBawFindPolygonIntersectionPoints(car(refObj) l1)
		
		if( clrcrs1 then clrLine1 = list(nth(0 clrPts)  caar(clrcrs1))  )
		if( clrcrs2 then clrLine2 = list(nth(2 clrPts)  caar(clrcrs2))  )

		if(clrLine2 && clrLine1 then clrLines = list( clrLine1  clrLine2 ) )		


		foreach(obj refObj dbDeleteObject(obj)) 
		foreach(obj obj3 dbDeleteObject(obj))   
		foreach(obj obj4 dbDeleteObject(obj))  
		foreach(obj obj6 dbDeleteObject(obj))  
		foreach(obj shpDonut dbDeleteObject(obj)) 

		if(orawMkr then
			foreach(obj obj7 dbDeleteObject(obj))
			foreach(inst ClrShp
				dbCreateProp(inst "Reverse_Angle_Collar_Marker" "boolean" t)  
			);;foreach
		else
			dbLayerAndNot(cellId "BAW_H3" ClrShp objA nc)
			;;add SVpos on MTE collar
			if(lyr == "BAW_MTE" then
				;;dbLayerAndNot(cellId "BAW_SVpos" ClrShp objA nc)
				;; 11/04/2025 by Matt, /b/a/w/p/d/k v0.14, svpos collar = MTE collar + 2.0
				dbLayerSize(cellId "BAW_SVpos" ClrShp 2.0 nc)
			);;if
			
			;;add NoMF4 for each line for DRC
			dbCreatePath(cellId "BAW_NoMF4" clrLine1 0.1)	
			dbCreatePath(cellId "BAW_NoMF4" clrLine2 0.1)
			
			
			foreach(inst ClrShp
				if(clrType == "MBE" then
					if(devType == "series" then 
				 		dbCreateProp(inst "BAW_SERIES_MBE_COLLAR" "boolean" t)  
				 	else
				 		dbCreateProp(inst "BAW_SHUNT_MBE_COLLAR" "boolean" t)  
				 	)
				 	dbCreateProp(inst "MBE_Collar_Points" "list" clrLines)
				else
					if(devType == "series" then 
			 			dbCreateProp(inst "BAW_SERIES_MTE_COLLAR" "boolean" t)  
			 		else
			 			dbCreateProp(inst "BAW_SHUNT_MTE_COLLAR" "boolean" t)  
			 		)
				);;if
			);;foreach



foreach(obj obj7 dbDeleteObject(obj)) 			
/*;; ADR 3.5, no M1/SV/PZL/Trim/etc on collars				
			;;add M1, SV and PZL collar		
			m1Out = dbLayerSize(cellId  "BAW_M1" ClrShp m1Eclrm1sv nc)  
			m1In1   = dbLayerSize(cellId  "BAW_M1" objA m1Eclr nc)   		 
			m1Clr_old = dbLayerAndNot(cellId "BAW_M1" m1Out m1In1 2*nc)
			
			svClr = dbLayerAndNot(cellId "BAW_SV" m1Out obj7 2*nc)
			dbLayerAndNot(cellId "BAW_H17" m1Out obj7 2*nc)
			
			clrLayerList = list("BAW_TFP" "BAW_ReF" "BAW_TF1" "BAW_TF2" "BAW_TF3" "BAW_TF4" "BAW_TF5" "BAW_TF6" "BAW_TF7" "BAW_TF8" "BAW_TFS" )
			foreach(ll clrLayerList dbLayerAndNot(cellId ll m1Out m1In1 2*nc) )

			foreach(obj m1Out dbDeleteObject(obj))
			foreach(obj m1In1 dbDeleteObject(obj)) 
			foreach(obj obj7 dbDeleteObject(obj)) 
			
			m1Clr = list()
			foreach(obj m1Clr_old 
				if( rdsCalcArea(obj) <=5.0 then 
					dbDeleteObject(obj)
				else
					m1Clr = append1(m1Clr  obj)
				)
			)
			
			if(clrType == "MTE" then
				pzlOut1 = dbLayerSize(cellId  "BAW_PZL" ClrShp pzlEclrEdge nc) 
				pzlOut2 = dbLayerSize(cellId "BAW_PZL" objA pzlEMTE nc)
				pzlIn  = dbLayerSize(cellId  "BAW_PZL" objA collarEnc nc)
				pzlClr1 = dbLayerAndNot(cellId "BAW_PZL" pzlOut2 pzlIn nc)
				pzlClr =  dbLayerAnd(cellId "BAW_PZL" pzlClr1 pzlOut1 2*nc)
				
				;;add ADL settings, pzl collar+3
				dbLayerSize(cellId "BAW_H12" pzlClr 3.0 2*nc)
				

				foreach(obj pzlOut1 dbDeleteObject(obj))
				foreach(obj pzlOut2 dbDeleteObject(obj))
				foreach(obj pzlIn dbDeleteObject(obj))
				foreach(obj pzlClr1 dbDeleteObject(obj))
			);;if
*/

		 	
		);;if
		

		
		/*;;create cut line for pin creation
		ctlp0 = rdsBawSkinnyExtendPoints( nth(2 clrPts) nth(0 clrPts) 4.0)
		ctlp2 = rdsBawSkinnyExtendPoints( nth(0 clrPts) nth(2 clrPts) 4.0)
		ctlp4 = rdsBawSkinnyExtendPoints( nth(2 clrPts) nth(0 clrPts) 4.0)
		ctlp6 = rdsBawSkinnyExtendPoints( nth(0 clrPts) nth(2 clrPts) 4.0)
		ctl1 = list(ctlp0 ctlp2)
		ctl2 = list(ctlp4 ctlp6)
		ctl = list(ctl1 ctl2)
		*/
		ctl = list()

		return(list(ptl shpOut clrLines  lcrsPts  ctl ClrShp ))		
	);;prog
);;proc


;;fwa = evalstring(ORaW)
procedure( rdsBawMultiCollarORaWBT(cellId objA fwa fwaBT nc @optional offsetlyr)
	prog( (orafBold orafB orafTold orafT obj shape fwaB fwaT mteClrShp mteSize orafShp negClrShp shp )
		if(evalstring(INFRA_ver) >= 4  then			
			orafB = setof( shape cellId~>shapes shape~>layerName=="BAW_H4" )
			orafT = setof( shape cellId~>shapes shape~>layerName=="BAW_H5" )
		else
			;;find H4, H5 shapes, merge, remove small pieces, reach orafB, orafT
			orafBold = setof( shape cellId~>shapes shape~>layerName=="BAW_H4" )
			orafB = dbLayerOr(cellId "BAW_H4" orafBold nil nc*2)
			orafTold = setof( shape cellId~>shapes shape~>layerName=="BAW_H5" )
			orafT = dbLayerOr(cellId "BAW_H5" orafTold nil nc*2)
			foreach(obj orafBold dbDeleteObject(obj))
			foreach(obj orafTold dbDeleteObject(obj))	
			orafB = setof( shape cellId~>shapes shape~>layerName=="BAW_H4" )
			orafT = setof( shape cellId~>shapes shape~>layerName=="BAW_H5" )
			foreach(obj orafB if(rdsCalcArea(obj) < 0.1 then dbDeleteObject(obj)) )
			foreach(obj orafT if(rdsCalcArea(obj) < 0.1 then dbDeleteObject(obj)) )
			orafB = setof( shape cellId~>shapes shape~>layerName=="BAW_H4" )
			orafT = setof( shape cellId~>shapes shape~>layerName=="BAW_H5" )
		);;if
		
 		if(offsetlyr then lyr = offsetlyr else lyr = "BAW_ORaF")		
		;;fwaBT<0 T higher than B, else B higher than T
		if(fwaBT < 0 then
			fwaB = fwa 
			fwaT = fwa+fwaBT
			mteClrShp = setof(shp cellId~>shapes shp~>layerName == "BAW_MTE" && ( exists( x shp~>prop~>name  list("BAW_SERIES_MTE_COLLAR")) || exists( x shp~>prop~>name   list("BAW_SHUNT_MTE_COLLAR")) ) )
			mteShps = append(objA mteClrShp)
			mteSize = dbLayerSize(cellId "y3" mteShps -fwa)			
			orafShp = dbLayerAnd(cellId lyr orafT mteSize)		
		else
			negClrShp = setof(shp cellId~>shapes shp~>layerName == "pin" &&  exists( x shp~>prop~>name  list("Reverse_Angle_Collar_Marker"))   )
			orafShp = dbLayerAndNot(cellId lyr orafB negClrShp)
			foreach(obj negClrShp dbDeleteObject(obj))
		);;if			
			
		foreach(shp cellId~>shapes if(rexMatchp( "BAW_H[4-6]" shp~>layerName) then dbDeleteObject(shp)) )
		foreach(shp cellId~>shapes if( rexMatchp("y[0-9]" shp~>layerName ) || rexMatchp("BAW_NoTF[0-9]" shp~>layerName) then dbDeleteObject(shp)) )
		
		;;dbCreatePolygon(cellId "BAW_ORaF"  orafPts )	
			
		return(orafShp)
	);;prog
);;proc





procedure(rdsBawXmlMultiCollarEMPort(cellId clrAngs resAA collarEnc nc)
	prog( (clrTB x clrs clrList clrTBNew clrsNew key newKey ele c1 c2 c3 maxAng indx tarAng tarLyr nextClr preClr 
			angPairs emp0 emp1 refp0 refp1 crsP0ExtNew crsP1ExtNew
			emp0Ext emp1Ext refp0Ext refp1Ext emLine refLine dist0 dist1 mindist nemLine pemLine ndist pdist
			crsPts crsP0 crsP1 crsP0Ext crsP1Ext emRuler emOver kpShps kpSize y0RulerPre y0Ruler crsCntr 
			emLineParlRot y1CrsPts	y1P0 y1P1 y1P0Dist y1P1Dist gloc
			)
		;;reset collar angles to within 0~360 range
		;;sort clrsNew by start angles, so eg. angle pair 355->10 will be the last
		/*not consider angle pair corresponding layer, re-write below
		clrs = foreach(mapcar x clrAngs car(x))
		clrList = copy(clrs)
		clrsNew = foreach(mapcar ele clrList mapcar( lambda( (x) if(x<0 then x+= 360 else x = x) if(x >360 then x-= 360 else x = x)) ele))
		clrsNew = sortcar(clrsNew 'lessp)
		*/
		
		clrTB = makeTable('clrTB "")
		foreach(mapcar x clrAngs clrTB[car(x)] = cadr(x))
		clrs = clrTB~>?
		clrList = copy(clrs)
		clrTBNew = makeTable('clrTBNew "")
		clrsNew = list()
		foreach(key clrList
			newKey = list()
			foreach(ele key
				if(ele < 0 then ele += 360)
				if(ele > 360 then ele -= 360)
				newKey = append1(newKey ele)
			);;foreach
			clrTBNew[newKey] = clrTB[key]
			clrsNew = append1(clrsNew newKey)
		);;foreach
		clrsNew = sortcar(clrsNew 'lessp)
		
		
		;;sort clrsNew to find max diff, assue max angle diff equals max perimeter of the collar
		;;get angle pair corresponding to max diff as target angle pair
		;;next angle pair of tarAng will be its next collar, previous angle pair of tarAng will be its previous collar 
		c1 = foreach(mapcar x clrsNew cadr(x)-car(x))
		c2 = foreach(mapcar x c1 if(x<0 then x+= 360.0 else x=x))
		c3 = copy(c2)
		maxAng = car(sort(c3 'greaterp))
		indx = lindex(c2 maxAng)
		tarAng = nth(indx-1 clrsNew)
		tarLyr = clrTBNew[tarAng]

		
		if(indx != length(clrsNew) then nextClr = car(nth(indx clrsNew))  else nextClr = caar(clrsNew))
		if(indx != 1 then preClr = cadr(nth(indx-2 clrsNew)) else preClr = cadar(last(clrsNew)) )
		
		angPairs = list( list(preClr car(tarAng))  list(cadr(tarAng) nextClr) ) 
		
		;;trapezoid shape from angle pairs
		;;base line will be a line connecting two points from target angle pair at active-1
		;;move base line (emLine) in parallel by 0.5*mindist
		;;mindist is min. distance from top/bottom side of the trapoziod shape or if mindist>14, mindist = 14
		emp0 = rdsBawXmlUserClrFindCrossingPointByAngle( list(resAA)  car(tarAng))
	    emp1 = rdsBawXmlUserClrFindCrossingPointByAngle( list(resAA)  cadr(tarAng))
	    refp0 = rdsBawXmlUserClrFindCrossingPointByAngle( list(resAA)  preClr)
	    refp1 = rdsBawXmlUserClrFindCrossingPointByAngle( list(resAA)  nextClr)

		
		emp0Ext = rdsBawSkinnyExtendPoints( emp0 emp1 20.0)
		emp1Ext = rdsBawSkinnyExtendPoints( emp1 emp0 20.0)
		refp0Ext = rdsBawSkinnyExtendPoints( refp0 refp1 20.0)
		refp1Ext = rdsBawSkinnyExtendPoints( refp1 refp0 20.0)
		emLine = list( emp0Ext emp1Ext ) 
		refLine = list( refp0Ext refp1Ext ) 
		dist0 = rdsBawDistOfPointToLine(emp0 refLine)
		dist1 = rdsBawDistOfPointToLine(emp1 refLine)
		mindist = floor(min(dist0 dist1))
		if(mindist >14.0 then misdist = 14.0)
			
		
		;;create pos and neg offset line by half mindist
		;;base line parallel line is the line that has min. distance between line and refp0
		nemLine = rdsBawOffSetLine( emLine 0.5*mindist )
		pemLine = rdsBawOffSetLine( emLine -0.5*mindist )		
		ndist = rdsBawDistOfPointToLine(refp0  nemLine)
		pdist = rdsBawDistOfPointToLine(refp0  pemLine)
		if(ndist < pdist then emLineParl = nemLine else emLineParl = pemLine)		
		;;find emLineParl center and create a path with 
		
		crsPts = rdsBawFindPolygonIntersectionPoints(resAA emLineParl)
		if(crsPts then
			crsP0 = caar(crsPts)
			crsP1 = caadr(crsPts)
			crsP0Ext = rdsBawSkinnyExtendPoints( crsP0  crsP1 0.8)
			crsP1Ext = rdsBawSkinnyExtendPoints( crsP1  crsP0 0.8)

		
			;;EM ruler	
			;;when em_hpt exceeds activeAA, shrink it by 10%
			emRuler = dbCreatePath(cellId "EM_HPT" list(crsP0Ext crsP1Ext) mindist+2.0)
			emOver = dbLayerAndNot(cellId "y2" list(emRuler) list(resAA) )
			emOverArea = rdsCalcArea(car(emOver))
			if(emOverArea then
				if( emOverArea > 8.0
					while(emOver 
						dbDeleteObject(emRuler)
						foreach(obj emOver dbDeleteObject(obj))
						crsP0ExtNew = rdsBawSkinnyExtendPoints( crsP0Ext  crsP1Ext 0.9)
						crsP1ExtNew = rdsBawSkinnyExtendPoints( crsP1Ext  crsP0Ext 0.9)
						crsP0Ext = crsP0ExtNew
						crsP1Ext = crsP1ExtNew
						emRuler = dbCreatePath(cellId "EM_HPT" list(crsP0Ext crsP1Ext) mindist+2.0)
						emOver = dbLayerAndNot(cellId "y2" list(emRuler) list(resAA) )		

					);;while
				);;if
			);;if
			foreach(obj emOver dbDeleteObject(obj))
			if(emRuler then emRuler = dbConvertPathToPolygon(emRuler) )
		);;if	
				
		;;y0 red ruler
		kpShps = setof(x cellId~>shapes rexMatchp("BAW_KpOut" x~>layerName) && rexMatchp("polygon" x~>objType) )
		
		/*kpShpMax = 0
		kpMax = car(kpShps)
		foreach(kp kpShps
			kpArea = rdsCalcArea(kp)
			if(kpArea > kpShpMax then kpShpMax = kpArea kpMax = kp)
		);;foreach
		
		y0Pts = rdsBawFindPolygonIntersectionPoints(kpMax emLineParl)
		y0P0 = caar(y0Pts)
		y0P1 = caadr(y0Pts)
		*/
		if(mindist < 2.0 then mindist = 2.0)
		kpSize = dbLayerSize(cellId "y2" kpShps -1.0 nc*2)
		y0RulerPre = dbCreatePath(cellId "y0" emLineParl mindist)
		y0RulerPre = dbConvertPathToPolygon(y0RulerPre)
		y0Ruler = dbLayerAnd(cellId "y0" list(y0RulerPre) kpSize )		
		dbDeleteObject(y0RulerPre)
		foreach(obj kpSize dbDeleteObject(obj))
		
		
		;;y1 yellow ruler
		;;rotate emLineParl by 90 degree to get y1 ruler
		if(crsPts then
			crsCntr = centerBox(list(crsP0 crsP1))
		else
			crsCntr = centerBox(resAA~>bBox)
		);;if
		emLineParlRot = rdsBawSkinnyRotateLine(car(emLineParl) cadr(emLineParl) 90.0  car(crsCntr) cadr(crsCntr))	
		y1CrsPts = rdsBawFindPolygonIntersectionPoints(car(y0Ruler) emLineParlRot)
		y1P0 = caar(y1CrsPts)
		y1P1 = caadr(y1CrsPts)
		dbCreateLine(cellId "y1" list(y1P0 y1P1 ) )
		
		
		;;G txt label
		y1P0Dist = rdsBawDistOfPointToLine(y1P0 emLine)
		y1P1Dist = rdsBawDistOfPointToLine(y1P1 emLine)
		;;if(y1P0Dist < y1P1Dist then gloc = y1P0 else gloc = y1P1)  ;;//cannot use close to base line, need to place towards MBE collar
		
		if(tarLyr == "BAW_MBE" then 
			if(y1P0Dist < y1P1Dist then gloc = y1P0 else gloc = y1P1)
		else
			if(y1P0Dist < y1P1Dist then gloc = y1P1 else gloc = y1P0)
		);;if
		dbCreateLabel(cellId  "text" gloc "G" "centerCenter"  "R0"  "stick" 2.0 )
		
		return( list(angPairs tarAng list(y1P0 y1P1 ) ) )
	);;prog
);;proc
