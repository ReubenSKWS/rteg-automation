procedure( rdsBawUpdateResonatorORaWBTGUI()
	let( (orawBT cv lcell libNames defaultLibName defaultCellName defaultViewName cellNames viewNames toplbl
			lName cNamelbl cName runlbl runList cNameAdd addtxt cNameRemove removetxt emplbl 
			fields form runChk rdsBawUpdateResonatorORaWBTForm form)
		cv = geGetEditCellView()
		lcell = setof(z ddGetLibList() !pcreMatchp("/rds" z~>readPath) )
        libNames = sort(lcell~>name 'alphalessp)      

        if(cv then
            defaultLibName  = cv~>libName
	        defaultCellName = cv~>cellName
	        defaultViewName = cv~>viewName
        else
	        defaultLibName  = car(reverse(libNames))
	        defaultCellName = car(ddGetObj(defaultLibName)~>cells)~>name
	        defaultViewName = car(ddGetObj(defaultLibName defaultCellName)~>views)~>name			
        )

        cellNames = sort(ddGetObj(defaultLibName)~>cells~>name 'alphalessp)                	
        viewNames = ddGetObj(defaultLibName defaultCellName)~>views~>name    
           
        orawBT = hiCreateStringField(  ?name           'orawBT
				     			      ?prompt         "ORaW Offset (MTE):"   
				     			      ?value          "-1.0"   	    		
           			      )   
		toplbl = hiCreateLabel( ?name 'toplbl
								?labelText "Please select TEGs:" 
								)	         
        lName = hiCreateCyclicField(  	?name           'lName
		             			        ?prompt         "Library:"
		             			        ?choices          libNames
		             			        ?value          defaultLibName                 
				                        ?callback	(lambda (field scope value )
						                            scope->cName->choices = sort(setof(z ddGetObj(value)~>cells~>name ddGetObj(value z "layout")
					                            								&& (rexMatchp("[rR]TEG1_" z) || rexMatchp("RefRes" z)) 
					                            								&& (!rexMatchp("_connect[MTE|MBE|PZL|\\_backup]" z) && !rexMatchp("_united" z) 
					                            								&& !rexMatchp("_THRU" z) && !pcreMatchp("RTEG[0-9]\\_(.*)\\_ORAW(.*)\\_" z)  )
					                            								 ) 'alphalessp)   					                                             
						                            scope->runList->value = nil
						                            scope->runList->choices = nil
						                            )      
                                    )                                     
        
		cNamelbl = hiCreateLabel( ?name 'cNamelbl
								?labelText "Cells:" 
									)
        cName = hiCreateListBoxField(?name           'cName
             			             ?prompt         ""
		                            ?multipleSelect t
		                            ?changeCB	"rdsFrameVarcNameCB()"
		                            ?choices 	sort(setof(z ddGetObj(defaultLibName)~>cells~>name ddGetObj(defaultLibName z "layout") 
                            							&& (rexMatchp("[rR]TEG1_" z)  || rexMatchp("RefRes" z))
                            							&& (!rexMatchp("_connect[MTE|MBE|PZL|\\_backup]" z) && !rexMatchp("_united" z) 
                            							&& !rexMatchp("_THRU" z) && !pcreMatchp("RTEG[0-9]\\_(.*)\\_ORAW(.*)\\_" z) ) 
                            							 ) 'alphalessp)                    
		                            )
	                            
        runlbl = hiCreateLabel( ?name 'runlbl
								?labelText "Cell List:"
								)
        runList = hiCreateListBoxField(?name           'runList
             			                ?prompt         ""
	                                    ?changeCB	"rdsFrameVarRunListCB()"
	                                    ?multipleSelect t
		                            	?choices 	sort(setof(z ddGetObj(defaultLibName)~>cells~>name ddGetObj(defaultLibName z "layout") 
                            							&& (rexMatchp("[rR]TEG1_" z)  || rexMatchp("RefRes" z))
                            							&& (!rexMatchp("_connect[MTE|MBE|PZL|\\_backup]" z) && !rexMatchp("_united" z) 
                            							&& !rexMatchp("_THRU" z) && !pcreMatchp("RTEG[0-9]\\_(.*)\\_ORAW(.*)\\_" z) ) 
                            							 ) 'alphalessp)          
                                    )
	                            
        cNameAdd = hiCreateButton(?name 		'cNameAdd
	                               ;; ?buttonText 	"Add Selected Cells to Cell List "
	                                ?buttonText 	"Add"
	                                ?buttonIcon   hiLoadIconFile("right-blue.png" 48 48)
	                                ?callback 	"rdsFrameVarAddSelectedCB()"
	                                ?enabled 	nil
	                                ?showTextWithIcon  t
	                            )

        addtxt = hiCreateLabel( ?name 'addtxt
								?labelText "Add"
										)
        cNameRemove = hiCreateButton( ?name 		'cNameRemove
	                               ;; ?buttonText 	"Remove Selected from Cell List"
	                                ?buttonText 	"Remove"
	                                ?buttonIcon     hiLoadIconFile("left-blue.png" 48 48)
	                                ?callback 	"rdsFrameVarRemoveSelectedCB()"
	                                ?enabled 	nil
	                                ?showTextWithIcon  t
	                            ) 
	    removetxt = hiCreateLabel( ?name 'removetxt
								?labelText "Remove"
										)    
		emplbl = hiCreateLabel( ?name 'emplbl
								?labelText " " 
								)								                            								                                               		                            
        fields = list(
                      list(toplbl  20:10 600:30 200 )   
                      list(lName  20:40 700:30 80 )
                      list(cNamelbl  20:70 400:30 80 ) 
			          list(cName  20:90 500:300 80 ) 
			          list(runlbl 620:70 500:30 80 ) 
			          list(runList 620:90 500:300 100 ) 
		              list(cNameAdd 550:140 150:30) 
			          list(cNameRemove 550:180 150:30)  
			          list(emplbl 580:400 580:20 250 )   
			          list(orawBT 20:430 400:30 150  )                                          			
                      )                                                
                      
                      
                      
        rdsBawUpdateResonatorORaWBTForm = hiCreateAppForm( ?name 'rdsBawUpdateResonatorORaWBTForm
                                       ?formTitle "Update resonators with ORaW offset (MTE)... "
                                       ?fields     fields    
                                       ?initialSize t
                                       ?callback "form = hiGetCurrentForm() 
                                       			rdsBawUpdateResonatorORaWBTCB(form) "
                                       ?buttonLayout 'OKCancelApply
                                       )        

        hiDisplayForm('rdsBawUpdateResonatorORaWBTForm)		
	
	);;let
);;proc


procedure( rdsBawUpdateResonatorORaWBTCB(form)
	prog( (orawBTValue cells techLib jm4sesets jm4shsets meshsesets meshshsets s3lay sh3lay sm3lay shm3lay
			vN cNames cName lName cv ints resList ele res cvid cvlay reses)
		orawBTValue = form~>orawBT~>value
		cells = form->runList->choices
		lName = form->lName->value
		techLib = getShellEnvVar("RDS_CDS_TECH")	
		jm4sesets = sort(setof(x ddGetObj(techLib)~>cells~>name rexMatchp("^series[0-9]$" x) ) 'alphalessp)
		jm4shsets = sort(setof(x ddGetObj(techLib)~>cells~>name rexMatchp("^shunt[0-9]$" x)  ) 'alphalessp)
		meshsesets = sort(setof(x ddGetObj(techLib)~>cells~>name rexMatchp("^seriesm[0-9]$" x) ) 'alphalessp)
		meshshsets = sort(setof(x ddGetObj(techLib)~>cells~>name rexMatchp("^shuntm[0-9]$" x)  ) 'alphalessp)
		
		vN = "layout"
		s3lay = dbOpenCellViewByType(techLib car(last(jm4sesets)) vN)
		sh3lay = dbOpenCellViewByType(techLib car(last(jm4shsets)) vN)
		sm3lay = dbOpenCellViewByType(techLib car(last(meshsesets)) vN)
		shm3lay = dbOpenCellViewByType(techLib car(last(meshshsets)) vN)
		foreach(cName cells
			cv = dbOpenCellViewByType(lName cName vN "maskLayout" "a")
			ints = dbInstQuery(cv cv~>bBox)		
			resList=setof(aa ints atom(aa)&&(rexMatchp("^series" aa~>cellName)||rexMatchp("^shunt" aa~>cellName)))
			foreach(res resList
				if(rexMatchp("^series[0-9]" res~>cellName)  	then	res~>master = s3lay 
				else if( rexMatchp("^shunt[0-9]" res~>cellName)  	then	res~>master = sh3lay 
					 else if(rexMatchp("^seriesm[0-9]" res~>cellName)  	then	res~>master = sm3lay 
					 	  else if(rexMatchp("^shuntm[0-9]" res~>cellName)  	then res~>master = shm3lay )
					 	  )
					 )
				);;if
				res~>ORaWBT = orawBTValue
			);;foreach
			printf("Changing %s ORaW Offset (MTE) to %s ...\n" cName  orawBTValue)
			dbSave(cv)
			dbClose(cv)		
		);;foreach
		dbClose(s3lay)
		dbClose(sh3lay)
		dbClose(sm3lay)
		dbClose(shm3lay)
	);;prog
);;proc
